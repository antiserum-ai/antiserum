"""SARIF 2.1.0 export. Extra file next to the receipt; no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.models import Flag, Pack, Receipt, Record
from antiserum.receipt import dumps as dumps_receipt
from antiserum.sarif import SARIF_SCHEMA, SARIF_VERSION, dumps, to_sarif, write_json
from antiserum.scan import scan


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


def _write_jsonl(folder: Path, rows: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "rows.jsonl"
    dest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return folder


def test_to_sarif_is_version_2_1_0() -> None:
    doc = to_sarif(_receipt())
    assert doc["version"] == SARIF_VERSION == "2.1.0"
    assert doc["$schema"] == SARIF_SCHEMA
    assert doc["runs"][0]["tool"]["driver"]["name"] == "antiserum"


def test_each_flag_is_a_result() -> None:
    receipt = _receipt(
        _flag("label_flips", "p-flip-1", "high", "minority label in a cluster"),
        _flag("stat_outliers", "p-stat-1", "medium", "length spike"),
        _flag("duplicate_inject", "p-dup-1", "low", "near-copy dump"),
    )
    results = to_sarif(receipt)["runs"][0]["results"]
    assert [item["ruleId"] for item in results] == [
        "duplicate_inject",
        "label_flips",
        "stat_outliers",
    ]
    by_rule = {item["ruleId"]: item for item in results}
    assert by_rule["label_flips"]["level"] == "error"
    assert by_rule["stat_outliers"]["level"] == "warning"
    assert by_rule["duplicate_inject"]["level"] == "note"
    assert by_rule["label_flips"]["message"]["text"] == "minority label in a cluster"
    assert by_rule["label_flips"]["locations"][0]["logicalLocations"][0]["name"] == (
        "p-flip-1"
    )


def test_location_uses_record_source_and_line() -> None:
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
    loc = to_sarif(receipt, records=records)["runs"][0]["results"][0]["locations"][0]
    assert loc["physicalLocation"]["artifactLocation"]["uri"] == (
        "corpus/toy/reviews.jsonl"
    )
    assert loc["physicalLocation"]["region"]["startLine"] == 12
    assert loc["logicalLocations"][0]["name"] == "p1"


def test_location_falls_back_to_receipt_path() -> None:
    loc = to_sarif(_receipt(_flag()))["runs"][0]["results"][0]["locations"][0]
    assert loc["physicalLocation"]["artifactLocation"]["uri"] == "mix"
    assert "region" not in loc["physicalLocation"]
    assert loc["logicalLocations"][0]["name"] == "p1"


def test_absolute_source_keeps_that_uri() -> None:
    receipt = _receipt(_flag(), path="mix")
    records = [
        Record(
            id="p1",
            text="plant",
            label=None,
            source="/data/reviews.jsonl",
            line=4,
        )
    ]
    loc = to_sarif(receipt, records=records)["runs"][0]["results"][0]["locations"][0]
    assert loc["physicalLocation"]["artifactLocation"]["uri"] == "/data/reviews.jsonl"


def test_single_file_scan_keeps_the_file_uri() -> None:
    receipt = _receipt(_flag(), path="data/rows.jsonl")
    records = [
        Record(id="p1", text="plant", label=None, source="rows.jsonl", line=3)
    ]
    loc = to_sarif(receipt, records=records)["runs"][0]["results"][0]["locations"][0]
    assert loc["physicalLocation"]["artifactLocation"]["uri"] == "data/rows.jsonl"
    assert loc["physicalLocation"]["region"]["startLine"] == 3


def test_empty_flags_still_valid_sarif() -> None:
    doc = to_sarif(_receipt())
    assert doc["runs"][0]["results"] == []
    assert doc["runs"][0]["tool"]["driver"]["rules"] == []


def test_dumps_is_deterministic() -> None:
    receipt = _receipt(
        _flag("stat_outliers", "b", "medium", "spike"),
        _flag("label_flips", "a", "high", "flip"),
    )
    assert dumps(receipt) == dumps(receipt)


def test_write_json_round_trip(tmp_path: Path) -> None:
    dest = tmp_path / "out.sarif"
    write_json(_receipt(_flag()), dest)
    obj = json.loads(dest.read_text(encoding="utf-8"))
    assert obj["version"] == "2.1.0"
    assert obj["runs"][0]["results"][0]["ruleId"] == "trigger_ngrams"


def test_scan_help_mentions_sarif(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--sarif" in text
    assert "SARIF 2.1.0" in text


def test_cli_writes_sarif_and_keeps_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "p1", "text": "row contains planted-sarif-marker-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-sarif-marker-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "receipt.json"
    sarif_path = tmp_path / "antiserum.sarif"
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--out",
            str(receipt_path),
            "--sarif",
            str(sarif_path),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "p1" in printed
    assert f"wrote {receipt_path}" in printed
    assert f"wrote {sarif_path}" in printed

    receipt_obj = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_obj["scanner"] == "antiserum"
    assert receipt_obj["flags"]
    assert "runs" not in receipt_obj

    sarif_obj = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert sarif_obj["version"] == "2.1.0"
    hit = next(
        item
        for item in sarif_obj["runs"][0]["results"]
        if item["locations"][0]["logicalLocations"][0]["name"] == "p1"
    )
    assert hit["ruleId"] == "signature_hit"
    assert hit["level"] == "error"
    assert "planted-sarif-marker-7f3a" in hit["message"]["text"]
    assert hit["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].endswith(
        "rows.jsonl"
    )
    assert hit["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1


def test_sarif_written_before_fail_exit(tmp_path: Path) -> None:
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
    sarif_path = tmp_path / "out.sarif"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--fail-on",
                "any",
                "--sarif",
                str(sarif_path),
            ]
        )
        == 1
    )
    obj = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert obj["runs"][0]["results"]


def test_json_stdout_unchanged_when_sarif_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [{"id": "c1", "text": "The coffee was warm this morning."}],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    sarif_path = tmp_path / "out.sarif"
    argv = [
        "scan",
        str(folder),
        "--feed",
        str(feed),
        "--json",
        "--sarif",
        str(sarif_path),
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    receipt = json.loads(printed)
    assert receipt["scanner"] == "antiserum"
    assert "runs" not in receipt
    expected = dumps_receipt(scan(folder, feed_path=feed))
    assert json.loads(printed) == json.loads(expected)
    assert sarif_path.is_file()
    assert json.loads(sarif_path.read_text(encoding="utf-8"))["version"] == "2.1.0"
