from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from antiserum.errors import AntiserumError
from antiserum.judge import utc_now
from antiserum.judgments import (
    FINAL_DECISIONS,
    JUDGES,
    Judgment,
    JudgmentStore,
    parse_flag_id,
)
from antiserum.models import Receipt

SCHEMA_ID = "antiserum.leftover_packet.v1"
DEFAULT_EXPORTER = "antiserum export-leftovers"
SCHEMA_FILENAME = "leftover-packet.schema.json"

CORPUS_TEXT_FIELDS = (
    "text",
    "label",
    "content",
    "instruction",
    "input",
    "output",
    "messages",
    "conversations",
    "prompt",
    "completion",
)


@dataclass(frozen=True)
class DecisionPatch:
    flag_id: str
    record_id: str
    check: str
    decision: str
    rationale: str
    judge: str
    timestamp: str
    proposed_signature: dict[str, Any] | None = None
    example_hashes: list[str] | None = None
    has_proposed: bool = False
    has_example_hashes: bool = False


@dataclass(frozen=True)
class MergeResult:
    updated: int
    created: int
    flag_ids: list[str]


def leftover_packet_schema_path() -> Path:
    """Published schema, or the copy shipped next to this module."""
    here = Path(__file__).resolve()
    repo_docs = here.parents[2] / "docs" / SCHEMA_FILENAME
    packaged = here.parent / SCHEMA_FILENAME
    if repo_docs.is_file():
        return repo_docs
    if packaged.is_file():
        return packaged
    raise AntiserumError(
        f"{SCHEMA_FILENAME} not found next to the package or under docs/"
    )


def load_schema() -> dict[str, Any]:
    path = leftover_packet_schema_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AntiserumError(f"{path}: invalid leftover-packet schema JSON") from exc


def dumps(packet: dict[str, Any]) -> str:
    return json.dumps(packet, indent=2, sort_keys=True)


def write_json(packet: dict[str, Any], path: Path) -> None:
    validate_packet(packet)
    path.write_text(dumps(packet) + "\n", encoding="utf-8")


def export_leftovers(
    store: JudgmentStore,
    *,
    receipt: Receipt | None = None,
    exported_at: str | None = None,
    exporter: str | None = DEFAULT_EXPORTER,
) -> dict[str, Any]:
    """Build antiserum.leftover_packet.v1 from needs_human rows only."""
    dataset_hash, scanner_version, pack = _header_from(store, receipt)
    leftovers = [_leftover_from_judgment(item) for item in store.leftovers()]
    packet: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "dataset_hash": dataset_hash,
        "scanner_version": scanner_version,
        "exported_at": exported_at or utc_now(),
        "leftovers": leftovers,
    }
    if pack is not None:
        packet["pack"] = pack
    if exporter:
        packet["exporter"] = exporter
    validate_packet(packet)
    return packet


def import_decisions(
    store: JudgmentStore,
    patches: list[DecisionPatch],
    *,
    allow_new: bool = False,
    now: str | None = None,
) -> MergeResult:
    """Merge final decisions into store by flag_id."""
    if not patches:
        raise AntiserumError("no decisions found")
    known = store.by_flag_id()
    unknown = [item.flag_id for item in patches if item.flag_id not in known]
    if unknown and not allow_new:
        listed = ", ".join(unknown)
        raise AntiserumError(
            f"unknown flag id(s): {listed}. pass --allow-new to append"
        )
    stamp = now or utc_now()
    updated = 0
    created = 0
    flag_ids: list[str] = []
    for item in patches:
        current = known.get(item.flag_id)
        if current is None:
            store.replace(_judgment_from_patch(item, stamp))
            created += 1
        else:
            store.replace(_merged_judgment(current, item, stamp))
            updated += 1
        flag_ids.append(item.flag_id)
        known = store.by_flag_id()
    return MergeResult(updated=updated, created=created, flag_ids=flag_ids)


def load_decisions(path: Path) -> list[DecisionPatch]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AntiserumError(f"decisions file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{path}: not valid UTF-8 text") from exc
    return loads_decisions(text, source=str(path))


def loads_decisions(text: str, *, source: str = "decisions") -> list[DecisionPatch]:
    stripped = text.strip()
    if not stripped:
        raise AntiserumError(f"{source}: decisions file is empty")
    if stripped[0] == "{":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return _load_decisions_jsonl(stripped, source)
        return _decisions_from_object(obj, source)
    if stripped[0] == "[":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AntiserumError(f"{source}: invalid JSON ({exc.msg})") from exc
        if not isinstance(obj, list):
            raise AntiserumError(f"{source}: expected a JSON array of decisions")
        return [_decision_from_obj(item, source) for item in obj]
    return _load_decisions_jsonl(stripped, source)


def validate_packet(packet: object) -> None:
    _assert_matches_schema(packet, load_schema())


def _header_from(
    store: JudgmentStore,
    receipt: Receipt | None,
) -> tuple[str, str | None, dict[str, str] | None]:
    dataset_hash = store.dataset_hash
    scanner_version = store.scanner_version
    pack = _pack_identity(store.pack)
    if receipt is not None:
        if (
            dataset_hash
            and receipt.dataset_hash
            and dataset_hash != receipt.dataset_hash
        ):
            raise AntiserumError(
                f"receipt dataset_hash {receipt.dataset_hash} does not match "
                f"judgments store ({dataset_hash})"
            )
        dataset_hash = receipt.dataset_hash
        scanner_version = receipt.version
        pack = _pack_identity(
            {"path": receipt.pack.path, "hash": receipt.pack.hash}
        )
    if not dataset_hash:
        raise AntiserumError(
            "dataset_hash is required; pass --receipt PATH or record it "
            "on the judgments store"
        )
    return dataset_hash, scanner_version, pack


def _pack_identity(obj: object) -> dict[str, str] | None:
    if not isinstance(obj, dict):
        return None
    path = obj.get("path")
    digest = obj.get("hash")
    if not isinstance(path, str) or not path.strip():
        return None
    if not isinstance(digest, str) or not digest.strip():
        return None
    return {"path": path, "hash": digest}


def _leftover_from_judgment(judgment: Judgment) -> dict[str, Any]:
    leftover: dict[str, Any] = {
        "flag_id": judgment.flag_id,
        "record_id": judgment.record_id,
        "check": judgment.check,
        "decision": judgment.decision,
        "rationale": judgment.rationale,
    }
    proposed = _sanitize_proposed(judgment.proposed_signature)
    if proposed is not None:
        leftover["proposed_signature"] = proposed
    hashes = _example_hashes(judgment, proposed)
    if hashes:
        leftover["example_hashes"] = hashes
    return leftover


def _example_hashes(
    judgment: Judgment, proposed: dict[str, Any] | None
) -> list[str]:
    if judgment.example_hashes:
        return [item for item in judgment.example_hashes if item]
    if proposed is None:
        return []
    raw = proposed.get("example_hashes")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item]


def _sanitize_proposed(obj: object) -> dict[str, Any] | None:
    if obj is None:
        return None
    if not isinstance(obj, dict):
        raise AntiserumError("proposed_signature must be an object")
    clean = {key: value for key, value in obj.items() if key not in CORPUS_TEXT_FIELDS}
    missing = [key for key in ("match", "pattern") if key not in clean]
    if missing:
        raise AntiserumError(
            f"proposed_signature missing {', '.join(missing)}"
        )
    return clean


def _decisions_from_object(obj: object, source: str) -> list[DecisionPatch]:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: decisions document must be a JSON object")
    schema = obj.get("schema")
    if schema == SCHEMA_ID:
        raise AntiserumError(
            f"{source}: import-decisions expects judgment-store JSON "
            "(or {schema, judgments|decisions}), not a leftover packet"
        )
    raw = obj.get("judgments")
    if raw is None:
        raw = obj.get("decisions")
    if raw is None and "flag_id" in obj:
        return [_decision_from_obj(obj, source)]
    if raw is None:
        raise AntiserumError(
            f"{source}: JSON object must be a judgments document, "
            "a decisions document, or a single judgment"
        )
    if not isinstance(raw, list):
        raise AntiserumError(f"{source}: 'judgments'/'decisions' must be a list")
    return [_decision_from_obj(item, source) for item in raw]


def _load_decisions_jsonl(text: str, source: str) -> list[DecisionPatch]:
    patches: list[DecisionPatch] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AntiserumError(
                f"{source}:{lineno}: invalid JSON ({exc.msg})"
            ) from exc
        patches.append(_decision_from_obj(obj, f"{source}:{lineno}"))
    if not patches:
        raise AntiserumError(f"{source}: no decision rows found")
    return patches


def _decision_from_obj(obj: object, source: str) -> DecisionPatch:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: each decision must be a JSON object")
    if "flag_id" not in obj:
        raise AntiserumError(f"{source}: decision missing required field 'flag_id'")
    flag = str(obj["flag_id"])
    check = str(obj["check"]) if obj.get("check") else ""
    record_id = str(obj["record_id"]) if obj.get("record_id") else ""
    if not check or not record_id:
        parsed_check, parsed_record = parse_flag_id(flag)
        check = check or parsed_check
        record_id = record_id or parsed_record
    if "decision" not in obj:
        raise AntiserumError(f"{source}: decision missing required field 'decision'")
    decision = str(obj["decision"])
    if decision not in FINAL_DECISIONS:
        raise AntiserumError(
            f"{source}: import-decisions requires a final decision "
            f"(poison, junk, or false_alarm); got {decision!r}"
        )
    rationale = obj.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise AntiserumError(f"{source}: 'rationale' must be a non-empty string")
    judge = str(obj["judge"]) if obj.get("judge") is not None else "human"
    if judge not in JUDGES:
        raise AntiserumError(f"{source}: 'judge' must be one of {', '.join(JUDGES)}")
    timestamp = str(obj["timestamp"]) if obj.get("timestamp") else utc_now()
    has_proposed = "proposed_signature" in obj
    proposed = obj.get("proposed_signature")
    if proposed is not None:
        proposed = _sanitize_proposed(proposed)
    hashes = None
    has_hashes = "example_hashes" in obj
    raw_hashes = obj.get("example_hashes")
    if raw_hashes is not None:
        hashes = _require_hashes(raw_hashes, source)
    return DecisionPatch(
        flag_id=flag,
        record_id=record_id,
        check=check,
        decision=decision,
        rationale=rationale.strip(),
        judge=judge,
        timestamp=timestamp,
        proposed_signature=proposed,
        example_hashes=hashes,
        has_proposed=has_proposed,
        has_example_hashes=has_hashes,
    )


def _require_hashes(obj: object, source: str) -> list[str]:
    if not isinstance(obj, list) or not all(
        isinstance(item, str) and item for item in obj
    ):
        raise AntiserumError(
            f"{source}: 'example_hashes' must be a list of non-empty strings"
        )
    return list(obj)


def _judgment_from_patch(item: DecisionPatch, stamp: str) -> Judgment:
    return Judgment(
        flag_id=item.flag_id,
        record_id=item.record_id,
        check=item.check,
        decision=item.decision,
        rationale=item.rationale,
        judge=item.judge,
        timestamp=item.timestamp or stamp,
        proposed_signature=item.proposed_signature,
        example_hashes=item.example_hashes,
    )


def _merged_judgment(
    current: Judgment, item: DecisionPatch, stamp: str
) -> Judgment:
    proposed = current.proposed_signature
    if item.has_proposed:
        proposed = item.proposed_signature
    hashes = current.example_hashes
    if item.has_example_hashes:
        hashes = item.example_hashes
    return Judgment(
        flag_id=current.flag_id,
        record_id=current.record_id,
        check=current.check,
        decision=item.decision,
        rationale=item.rationale,
        judge=item.judge,
        timestamp=item.timestamp or stamp,
        proposed_signature=proposed,
        example_hashes=hashes,
    )


def _assert_matches_schema(
    instance: object,
    schema: dict[str, Any],
    *,
    root: dict[str, Any] | None = None,
    path: str = "$",
) -> None:
    root = schema if root is None else root
    schema = _resolve(schema, root)

    expected = schema.get("type")
    if expected is not None:
        types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_is_type(instance, name) for name in types):
            raise AntiserumError(
                f"{path}: expected type {types}, got {type(instance).__name__}"
            )

    if "const" in schema and instance != schema["const"]:
        raise AntiserumError(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise AntiserumError(f"{path}: {instance!r} not in {schema['enum']}")

    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(
        instance, bool
    ):
        if instance < schema["minimum"]:
            raise AntiserumError(f"{path}: {instance} < minimum {schema['minimum']}")
    if "maximum" in schema and isinstance(instance, (int, float)) and not isinstance(
        instance, bool
    ):
        if instance > schema["maximum"]:
            raise AntiserumError(f"{path}: {instance} > maximum {schema['maximum']}")
    if "minLength" in schema and isinstance(instance, str):
        if len(instance) < schema["minLength"]:
            raise AntiserumError(f"{path}: string shorter than minLength")

    if isinstance(instance, dict):
        missing = [key for key in schema.get("required", []) if key not in instance]
        if missing:
            raise AntiserumError(
                f"{path}: missing required field(s): {', '.join(missing)}"
            )
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                _assert_matches_schema(
                    value, props[key], root=root, path=f"{path}.{key}"
                )
            elif additional is False:
                raise AntiserumError(
                    f"{path}: additional property {key!r} not allowed"
                )
            elif isinstance(additional, dict):
                _assert_matches_schema(
                    value, additional, root=root, path=f"{path}.{key}"
                )

    if isinstance(instance, list) and "items" in schema:
        item_schema = schema["items"]
        for i, item in enumerate(instance):
            _assert_matches_schema(
                item, item_schema, root=root, path=f"{path}[{i}]"
            )


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise AntiserumError(f"unsupported schema $ref: {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise AntiserumError(f"unresolved schema $ref: {ref}")
        node = node[part]
    if not isinstance(node, dict):
        raise AntiserumError(f"schema $ref {ref} is not an object")
    return node


def _is_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise AntiserumError(f"unsupported schema type: {expected}")
