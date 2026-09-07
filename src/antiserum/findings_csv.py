"""CSV findings table from a scan receipt. Local file only. No network."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path

from antiserum.models import Flag, Receipt, Record

COLUMNS = (
    "record_id",
    "check",
    "severity",
    "reason",
    "source",
    "line",
)


def write_csv(
    receipt: Receipt,
    path: Path,
    records: Sequence[Record] | None = None,
) -> None:
    Path(path).write_text(dumps(receipt, records=records), encoding="utf-8")


def dumps(receipt: Receipt, records: Sequence[Record] | None = None) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows(receipt, records=records))
    return buf.getvalue()


def rows(
    receipt: Receipt, records: Sequence[Record] | None = None
) -> list[dict[str, str]]:
    by_id = _index_records(records)
    return [
        _row(flag, by_id.get(flag.record_id))
        for flag in sorted(receipt.flags, key=lambda f: f.sort_key())
    ]


def _row(flag: Flag, record: Record | None) -> dict[str, str]:
    source = record.source if record is not None else ""
    line = ""
    if record is not None and record.line is not None:
        line = str(record.line)
    return {
        "record_id": flag.record_id,
        "check": flag.check,
        "severity": flag.severity,
        "reason": flag.reason,
        "source": source,
        "line": line,
    }


def _index_records(records: Sequence[Record] | None) -> dict[str, Record]:
    if not records:
        return {}
    index: dict[str, Record] = {}
    for rec in records:
        index.setdefault(rec.id, rec)
    return index
