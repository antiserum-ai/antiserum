from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from antiserum.errors import AntiserumError
from antiserum.models import Flag, Receipt, SignatureHit


def write_json(receipt: Receipt, path: Path) -> None:
    path.write_text(dumps(receipt) + "\n", encoding="utf-8")


def dumps(receipt: Receipt) -> str:
    return json.dumps(receipt.to_json_obj(), indent=2, sort_keys=True)


def load_json(path: Path) -> Receipt:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AntiserumError(f"receipt not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{path}: not valid UTF-8 text") from exc
    return loads(text, source=str(path))


def loads(text: str, *, source: str = "receipt") -> Receipt:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AntiserumError(f"{source}: invalid JSON ({exc.msg})") from exc
    return from_json_obj(obj, source=source)


def from_json_obj(obj: object, *, source: str = "receipt") -> Receipt:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: receipt must be a JSON object")
    required = ("scanner", "version", "path", "dataset_hash", "record_count")
    missing = [k for k in required if k not in obj]
    if missing:
        raise AntiserumError(
            f"{source}: missing required field(s): {', '.join(missing)}"
        )
    flags = [_flag_from_obj(item, source) for item in _as_list(obj.get("flags"), "flags", source)]
    hits = [
        _hit_from_obj(item, source)
        for item in _as_list(obj.get("signature_hits"), "signature_hits", source)
    ]
    try:
        record_count = int(obj["record_count"])
    except (TypeError, ValueError) as exc:
        raise AntiserumError(f"{source}: 'record_count' must be an integer") from exc
    return Receipt(
        scanner=str(obj["scanner"]),
        version=str(obj["version"]),
        path=str(obj["path"]),
        dataset_hash=str(obj["dataset_hash"]),
        record_count=record_count,
        flags=flags,
        signature_hits=hits,
    )


def _as_list(value: object, field: str, source: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AntiserumError(f"{source}: '{field}' must be a list")
    return value


def _flag_from_obj(obj: object, source: str) -> Flag:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: each flag must be a JSON object")
    missing = [k for k in ("check", "record_id", "severity", "reason") if k not in obj]
    if missing:
        raise AntiserumError(
            f"{source}: flag missing required field(s): {', '.join(missing)}"
        )
    evidence = obj.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise AntiserumError(f"{source}: flag 'evidence' must be an object")
    return Flag(
        check=str(obj["check"]),
        record_id=str(obj["record_id"]),
        severity=str(obj["severity"]),
        reason=str(obj["reason"]),
        evidence=evidence,
    )


def _hit_from_obj(obj: object, source: str) -> SignatureHit:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: each signature hit must be a JSON object")
    missing = [k for k in ("signature_id", "record_id", "pattern", "match") if k not in obj]
    if missing:
        raise AntiserumError(
            f"{source}: signature hit missing required field(s): {', '.join(missing)}"
        )
    confidence = obj.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
    ):
        raise AntiserumError(f"{source}: signature hit 'confidence' must be a number")
    attack = obj.get("attack")
    return SignatureHit(
        signature_id=str(obj["signature_id"]),
        record_id=str(obj["record_id"]),
        attack=str(attack) if isinstance(attack, str) else None,
        pattern=str(obj["pattern"]),
        match=str(obj["match"]),
        confidence=float(confidence)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else None,
    )


def format_text(receipt: Receipt) -> str:
    lines = [
        f"antiserum {receipt.version}",
        f"scan: {receipt.path}",
        f"records: {receipt.record_count}",
        f"dataset_hash: {receipt.dataset_hash}",
        "",
        f"flags: {len(receipt.flags)}",
    ]
    if receipt.flags:
        for flag in sorted(receipt.flags, key=lambda f: f.sort_key()):
            lines.append(
                f"  {flag.record_id}  {flag.check}  {flag.severity}  {flag.reason}"
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"signature_hits: {len(receipt.signature_hits)}")
    if receipt.signature_hits:
        for hit in sorted(receipt.signature_hits, key=lambda h: h.sort_key()):
            attack = hit.attack or "-"
            lines.append(
                f"  {hit.record_id}  {hit.signature_id}  {attack}  "
                f"matched {hit.match} {hit.pattern!r}"
            )
    else:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"
