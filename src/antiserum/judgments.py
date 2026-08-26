from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from antiserum.errors import AntiserumError

SCHEMA_ID = "antiserum.judgments.v1"
DECISIONS = ("poison", "junk", "false_alarm", "needs_human")
FINAL_DECISIONS = ("poison", "junk", "false_alarm")
JUDGES = ("agent", "human")


def flag_id(check: str, record_id: str) -> str:
    return f"{check}:{record_id}"


def parse_flag_id(value: str) -> tuple[str, str]:
    check, sep, record_id = value.partition(":")
    if not sep or not check.strip() or not record_id.strip():
        raise AntiserumError(
            f"invalid flag id {value!r}; expected '<check>:<record_id>'"
        )
    return check, record_id


@dataclass
class Judgment:
    flag_id: str
    record_id: str
    check: str
    decision: str
    rationale: str
    judge: str
    timestamp: str
    proposed_signature: dict[str, Any] | None = None

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "flag_id": self.flag_id,
            "record_id": self.record_id,
            "check": self.check,
            "decision": self.decision,
            "rationale": self.rationale,
            "proposed_signature": self.proposed_signature,
            "judge": self.judge,
            "timestamp": self.timestamp,
        }


@dataclass
class JudgmentStore:
    path: str
    dataset_hash: str
    judgments: list[Judgment] = field(default_factory=list)
    receipt: str | None = None
    scanner_version: str | None = None
    schema: str = SCHEMA_ID

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "path": self.path,
            "receipt": self.receipt,
            "dataset_hash": self.dataset_hash,
            "scanner_version": self.scanner_version,
            "judgments": [j.to_json_obj() for j in self.sorted_judgments()],
        }

    def sorted_judgments(self) -> list[Judgment]:
        return sorted(self.judgments, key=lambda j: (j.check, j.record_id, j.flag_id))

    def by_flag_id(self) -> dict[str, Judgment]:
        return {j.flag_id: j for j in self.judgments}

    def leftovers(self) -> list[Judgment]:
        return [j for j in self.sorted_judgments() if j.decision == "needs_human"]

    def replace(self, judgment: Judgment) -> None:
        found = False
        updated: list[Judgment] = []
        for item in self.judgments:
            if item.flag_id == judgment.flag_id:
                updated.append(judgment)
                found = True
            else:
                updated.append(item)
        if not found:
            updated.append(judgment)
        self.judgments = updated


def dumps(store: JudgmentStore) -> str:
    return json.dumps(store.to_json_obj(), indent=2, sort_keys=True)


def write_json(store: JudgmentStore, path: Path) -> None:
    path.write_text(dumps(store) + "\n", encoding="utf-8")


def write_jsonl(store: JudgmentStore, path: Path) -> None:
    lines = [
        json.dumps(j.to_json_obj(), sort_keys=True, separators=(",", ":"))
        for j in store.sorted_judgments()
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load(path: Path) -> JudgmentStore:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AntiserumError(f"judgments file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{path}: not valid UTF-8 text") from exc
    return loads(text, source=str(path))


def loads(text: str, *, source: str = "judgments") -> JudgmentStore:
    stripped = text.strip()
    if not stripped:
        raise AntiserumError(f"{source}: judgments file is empty")
    if stripped[0] == "{":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return _load_jsonl(stripped, source)
        if "judgments" in obj or "schema" in obj:
            return _store_from_obj(obj, source)
        if "flag_id" in obj:
            return JudgmentStore(
                path="",
                dataset_hash="",
                judgments=[_judgment_from_obj(obj, source)],
            )
        raise AntiserumError(
            f"{source}: JSON object must be a judgments document or a single judgment"
        )
    if stripped[0] == "[":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AntiserumError(f"{source}: invalid JSON ({exc.msg})") from exc
        if not isinstance(obj, list):
            raise AntiserumError(f"{source}: expected a JSON array of judgments")
        return JudgmentStore(
            path="",
            dataset_hash="",
            judgments=[_judgment_from_obj(item, source) for item in obj],
        )
    return _load_jsonl(stripped, source)


def _load_jsonl(text: str, source: str) -> JudgmentStore:
    judgments: list[Judgment] = []
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
        judgments.append(_judgment_from_obj(obj, f"{source}:{lineno}"))
    if not judgments:
        raise AntiserumError(f"{source}: no judgment rows found")
    return JudgmentStore(path="", dataset_hash="", judgments=judgments)


def _store_from_obj(obj: object, source: str) -> JudgmentStore:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: judgments document must be a JSON object")
    raw_judgments = obj.get("judgments")
    if raw_judgments is None:
        raise AntiserumError(f"{source}: missing required field 'judgments'")
    if not isinstance(raw_judgments, list):
        raise AntiserumError(f"{source}: 'judgments' must be a list")
    judgments = [_judgment_from_obj(item, source) for item in raw_judgments]
    return JudgmentStore(
        schema=str(obj.get("schema") or SCHEMA_ID),
        path=str(obj.get("path") or ""),
        receipt=str(obj["receipt"]) if obj.get("receipt") is not None else None,
        dataset_hash=str(obj.get("dataset_hash") or ""),
        scanner_version=(
            str(obj["scanner_version"]) if obj.get("scanner_version") is not None else None
        ),
        judgments=judgments,
    )


def _judgment_from_obj(obj: object, source: str) -> Judgment:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: each judgment must be a JSON object")
    required = (
        "flag_id",
        "record_id",
        "check",
        "decision",
        "rationale",
        "judge",
        "timestamp",
    )
    missing = [k for k in required if k not in obj]
    if missing:
        raise AntiserumError(
            f"{source}: judgment missing required field(s): {', '.join(missing)}"
        )
    decision = str(obj["decision"])
    if decision not in DECISIONS:
        raise AntiserumError(
            f"{source}: 'decision' must be one of {', '.join(DECISIONS)}"
        )
    judge = str(obj["judge"])
    if judge not in JUDGES:
        raise AntiserumError(f"{source}: 'judge' must be one of {', '.join(JUDGES)}")
    rationale = obj["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise AntiserumError(f"{source}: 'rationale' must be a non-empty string")
    proposed = obj.get("proposed_signature")
    if proposed is not None:
        proposed = _validate_proposed(proposed, source)
    return Judgment(
        flag_id=str(obj["flag_id"]),
        record_id=str(obj["record_id"]),
        check=str(obj["check"]),
        decision=decision,
        rationale=rationale.strip(),
        judge=judge,
        timestamp=str(obj["timestamp"]),
        proposed_signature=proposed,
    )


def _validate_proposed(obj: object, source: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: 'proposed_signature' must be an object")
    missing = [k for k in ("match", "pattern") if k not in obj]
    if missing:
        raise AntiserumError(
            f"{source}: proposed_signature missing {', '.join(missing)}"
        )
    if not isinstance(obj["match"], str) or not obj["match"].strip():
        raise AntiserumError(f"{source}: proposed_signature 'match' must be a string")
    if not isinstance(obj["pattern"], str) or not obj["pattern"]:
        raise AntiserumError(
            f"{source}: proposed_signature 'pattern' must be a non-empty string"
        )
    return obj


def format_text(store: JudgmentStore) -> str:
    counts = {key: 0 for key in DECISIONS}
    for judgment in store.judgments:
        counts[judgment.decision] = counts.get(judgment.decision, 0) + 1
    lines = [
        f"judgments: {len(store.judgments)}",
        f"  poison: {counts['poison']}",
        f"  junk: {counts['junk']}",
        f"  false_alarm: {counts['false_alarm']}",
        f"  needs_human: {counts['needs_human']}",
        "",
    ]
    if not store.judgments:
        lines.append("  (none)")
        return "\n".join(lines) + "\n"
    for judgment in store.sorted_judgments():
        extra = ""
        if judgment.proposed_signature:
            extra = f"  sig {judgment.proposed_signature.get('match')} {judgment.proposed_signature.get('pattern')!r}"
        lines.append(
            f"  {judgment.flag_id}  {judgment.decision}  {judgment.judge}  "
            f"{judgment.rationale}{extra}"
        )
    leftovers = store.leftovers()
    if leftovers:
        lines.append("")
        lines.append(f"leftovers: {len(leftovers)} (settle with antiserum confirm)")
        for judgment in leftovers:
            lines.append(f"  {judgment.flag_id}")
    return "\n".join(lines) + "\n"
