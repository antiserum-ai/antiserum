"""CSV findings table from scan. Extra file next to the receipt; no network."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.findings_csv import COLUMNS, dumps, rows, write_csv
from antiserum.models import Flag, Pack, Receipt, Record
from antiserum.receipt import dumps as dumps_receipt
from antiserum.scan import scan

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _receipt(*flags: Flag, path: str = "mix") -> Receipt:
    return Receipt(
        scanner="antiserum",
        version="0.1.0",
        path=path,
        dataset_hash="sha256:x",
        record_count=1,
        flags=list(flags),
        signature_hits=[],
        pack=Pack.none(),
    )


def _flag(
    check: str = "trigger_ngrams",
    record_id: str = "p1",
    severity: str = "high",
    reason: str = "planted trigger",
) -> Flag:
    return Flag(
        check=check,
        record_id=record_id,
        severity=severity,
        reason=reason,
    )


def _write_jsonl(folder: Path, rows_data: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "rows.jsonl"
    dest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows_data),
        encoding="utf-8",
    )
    return folder


def _parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_columns_are_stable() -> None:
    assert COLUMNS == (
        "record_id",
        "check",
        "severity",
        "reason",
        "source",
        "line",
    )


def test_one_row_per_flag_sorted() -> None:
    receipt = _receipt(
        _flag("stat_outliers", "p-stat-1", "medium", "length spike"),
        _flag("label_flips", "p-flip-1", "high", "minority label in a cluster"),
        _flag("duplicate_inject", "p-dup-1", "low", "near-copy dump"),
    )
    table = rows(receipt)
    assert [item["record_id"] for item in table] == [
        "p-dup-1",
        "p-flip-1",
        "p-stat-1",
    ]
    assert [item["check"] for item in table] == [
        "duplicate_inject",
        "label_flips",
        "stat_outliers",
    ]
    by_id = {item["record_id"]: item for item in table}
    assert by_id["p-flip-1"]["severity"] == "high"
    assert by_id["p-flip-1"]["reason"] == "minority label in a cluster"
    assert by_id["p-flip-1"]["source"] == ""
    assert by_id["p-flip-1"]["line"] == ""


def test_empty_flags_writes_header_only() -> None:
    text = dumps(_receipt())
    assert text == "record_id,check,severity,reason,source,line\n"
    assert _parse(text) == []


def test_source_and_line_from_records() -> None:
    receipt = _receipt(_flag(), path="corpus/toy")
    records = [
        Record(
            id="p1",
            text="plant",
            label=None,
            source="reviews.jsonl",
            line=12,
        )
    ]
    row = rows(receipt, records=records)[0]
    assert row["source"] == "reviews.jsonl"
    assert row["line"] == "12"
    assert row["record_id"] == "p1"


def test_reason_with_comma_and_quote_is_escaped() -> None:
    receipt = _receipt(
        _flag(reason='saw "ignore previous", then a payload')
    )
    parsed = _parse(dumps(receipt))
    assert parsed[0]["reason"] == 'saw "ignore previous", then a payload'


def test_dumps_is_deterministic() -> None:
    receipt = _receipt(
        _flag("stat_outliers", "b", "medium", "spike"),
        _flag("label_flips", "a", "high", "flip"),
    )
    assert dumps(receipt) == dumps(receipt)
    assert dumps(receipt).startswith("record_id,check,severity,reason,source,line\n")


def test_write_csv_round_trip(tmp_path: Path) -> None:
    dest = tmp_path / "findings.csv"
    write_csv(_receipt(_flag()), dest)
    parsed = _parse(dest.read_text(encoding="utf-8"))
    assert parsed[0]["record_id"] == "p1"
    assert parsed[0]["check"] == "trigger_ngrams"
    assert parsed[0]["severity"] == "high"
    assert parsed[0]["reason"] == "planted trigger"


def test_scan_help_mentions_csv(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--csv" in text
    assert "CSV findings table" in text
    assert "nothing is uploaded" in text


def test_cli_writes_csv_and_keeps_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "p1", "text": "row contains planted-csv-marker-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-csv-marker-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "receipt.json"
    csv_path = tmp_path / "findings.csv"
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--out",
            str(receipt_path),
            "--csv",
            str(csv_path),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "p1" in printed
    assert f"wrote {receipt_path}" in printed
    assert f"wrote {csv_path}" in printed

    receipt_obj = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_obj["scanner"] == "antiserum"
    assert receipt_obj["flags"]
    assert "record_id,check" not in json.dumps(receipt_obj)

    parsed = _parse(csv_path.read_text(encoding="utf-8"))
    hit = next(item for item in parsed if item["record_id"] == "p1")
    assert hit["check"] == "signature_hit"
    assert hit["severity"] == "high"
    assert "planted-csv-marker-7f3a" in hit["reason"]
    assert hit["source"].endswith("rows.jsonl")
    assert int(hit["line"]) >= 1


def test_csv_written_before_fail_exit(tmp_path: Path) -> None:
    folder = _write_jsonl(
        tmp_path / "high",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "p1", "text": "row contains planted-high-marker-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-high-marker-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "findings.csv"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--fail-on",
                "any",
                "--csv",
                str(csv_path),
            ]
        )
        == 1
    )
    parsed = _parse(csv_path.read_text(encoding="utf-8"))
    assert parsed
    assert parsed[0]["record_id"] == "p1"


def test_json_stdout_unchanged_when_csv_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [{"id": "c1", "text": "The coffee was warm this morning."}],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    csv_path = tmp_path / "findings.csv"
    argv = [
        "scan",
        str(folder),
        "--feed",
        str(feed),
        "--json",
        "--csv",
        str(csv_path),
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    receipt = json.loads(printed)
    assert receipt["scanner"] == "antiserum"
    expected = dumps_receipt(scan(folder, feed_path=feed))
    assert json.loads(printed) == json.loads(expected)
    assert csv_path.is_file()
    assert csv_path.read_text(encoding="utf-8") == (
        "record_id,check,severity,reason,source,line\n"
    )
    assert "wrote " not in printed


def test_readme_documents_csv() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--csv findings.csv" in text
    assert "`record_id`" in text
    assert "`check`" in text
    assert "`severity`" in text
    assert "`reason`" in text
    assert "header only" in text
    assert "--out" in text
    assert "--sarif" in text
    assert "--html" in text
    assert "--md" in text
