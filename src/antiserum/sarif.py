"""SARIF 2.1.0 export of a scan receipt. Local file only. No network."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from antiserum.models import Flag, Receipt, Record

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/"
    "sarif-schema-2.1.0.json"
)
# Static homepage string on the tool driver. Writing a file does not fetch it.
INFORMATION_URI = "https://github.com/antiserum-ai/antiserum"

# File suffixes ingest treats as a single source file (not a folder).
_FILE_SUFFIXES = {".jsonl", ".txt", ".arrow", ".parquet"}

_LEVEL = {
    "high": "error",
    "medium": "warning",
    "low": "note",
}


def write_json(
    receipt: Receipt,
    path: Path,
    records: Sequence[Record] | None = None,
) -> None:
    path.write_text(dumps(receipt, records=records) + "\n", encoding="utf-8")


def dumps(receipt: Receipt, records: Sequence[Record] | None = None) -> str:
    return json.dumps(
        to_sarif(receipt, records=records), indent=2, sort_keys=True
    )


def to_sarif(
    receipt: Receipt, records: Sequence[Record] | None = None
) -> dict[str, Any]:
    by_id = _index_records(records)
    flags = sorted(receipt.flags, key=lambda f: f.sort_key())
    rule_ids = sorted({flag.check for flag in flags})
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "results": [
                    _result(flag, receipt, by_id.get(flag.record_id))
                    for flag in flags
                ],
                "tool": {
                    "driver": {
                        "informationUri": INFORMATION_URI,
                        "name": receipt.scanner,
                        "rules": [_rule(rule_id) for rule_id in rule_ids],
                        "version": receipt.version,
                    }
                },
            }
        ],
    }


def _index_records(
    records: Sequence[Record] | None,
) -> dict[str, Record]:
    if not records:
        return {}
    index: dict[str, Record] = {}
    for rec in records:
        index.setdefault(rec.id, rec)
    return index


def _rule(rule_id: str) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": rule_id,
        "shortDescription": {"text": rule_id},
    }


def _result(
    flag: Flag, receipt: Receipt, record: Record | None
) -> dict[str, Any]:
    return {
        "level": _LEVEL.get(flag.severity, "warning"),
        "locations": [_location(flag, receipt, record)],
        "message": {"text": flag.reason},
        "ruleId": flag.check,
    }


def _location(
    flag: Flag, receipt: Receipt, record: Record | None
) -> dict[str, Any]:
    source = record.source if record is not None else None
    line = record.line if record is not None else None
    physical: dict[str, Any] = {
        "artifactLocation": {"uri": _artifact_uri(receipt.path, source)},
    }
    if line is not None and line >= 1:
        physical["region"] = {"startLine": line}
    return {
        "logicalLocations": [{"name": flag.record_id}],
        "physicalLocation": physical,
    }


def _artifact_uri(receipt_path: str, source: str | None) -> str:
    root = Path(receipt_path)
    if not source:
        return root.as_posix()
    src = Path(source)
    if src.is_absolute():
        return src.as_posix()
    if root.suffix.lower() in _FILE_SUFFIXES or root.name == src.name:
        return root.as_posix()
    return (root / src).as_posix()
