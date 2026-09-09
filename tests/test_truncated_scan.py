"""Scan fail-closed when a row or byte ceiling stops ingest (#85)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.receipt import dumps, format_text
from antiserum.scan import EXIT_TRUNCATED, scan


def _write_rows(folder: Path, rows: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "rows.jsonl"
    dest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return folder


def _clean_rows(n: int) -> list[dict]:
    return [
        {"id": f"c{i}", "text": f"The coffee was warm this morning number {i}."}
        for i in range(n)
    ]


def _empty_feed(tmp_path: Path) -> Path:
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    return feed


def test_under_ceiling_exits_zero_and_omits_truncated(tmp_path: Path) -> None:
    folder = _write_rows(tmp_path / "mix", _clean_rows(3))
    feed = _empty_feed(tmp_path)
    out = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--max-records",
                "10",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert "truncated" not in obj
    assert obj["record_count"] == 3
    receipt = scan(folder, feed_path=feed, max_records=10)
    assert receipt.truncated is None
    assert "truncated:" not in format_text(receipt)


def test_over_record_ceiling_fails_closed_unless_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_rows(tmp_path / "mix", _clean_rows(3))
    feed = _empty_feed(tmp_path)
    out = tmp_path / "receipt.json"
    argv = [
        "scan",
        str(folder),
        "--feed",
        str(feed),
        "--max-records",
        "1",
        "--out",
        str(out),
    ]
    assert main(argv) == EXIT_TRUNCATED
    text = capsys.readouterr().out
    assert "truncated:" in text
    assert "records ceiling" in text
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["truncated"]["ceiling"] == "records"
    assert obj["truncated"]["records_seen"] == 1
    assert obj["truncated"]["bytes_seen"] > 0
    assert obj["record_count"] == 1

    assert main(argv + ["--allow-truncated"]) == 0
    allowed = capsys.readouterr().out
    assert "truncated:" in allowed
    again = json.loads(out.read_text(encoding="utf-8"))
    assert again["truncated"]["ceiling"] == "records"


def test_over_byte_ceiling_fails_closed_unless_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = json.dumps({"id": "c0", "text": "The coffee was warm this morning."}) + "\n"
    second = json.dumps({"id": "c1", "text": "I waited twenty minutes for lunch."}) + "\n"
    folder = tmp_path / "mix"
    folder.mkdir()
    (folder / "rows.jsonl").write_text(first + second, encoding="utf-8")
    feed = _empty_feed(tmp_path)
    limit = str(len(first.encode("utf-8")))
    out = tmp_path / "receipt.json"
    argv = [
        "scan",
        str(folder),
        "--feed",
        str(feed),
        "--max-bytes",
        limit,
        "--json",
        "--out",
        str(out),
    ]
    assert main(argv) == EXIT_TRUNCATED
    obj = json.loads(capsys.readouterr().out)
    assert obj["truncated"]["ceiling"] == "bytes"
    assert obj["truncated"]["records_seen"] == 1
    assert obj["truncated"]["bytes_seen"] == len(first.encode("utf-8"))
    assert obj["record_count"] == 1
    assert main(argv + ["--allow-truncated"]) == 0
    allowed = json.loads(capsys.readouterr().out)
    assert allowed["truncated"]["ceiling"] == "bytes"


def test_allow_truncated_still_applies_fail_on(
    tmp_path: Path,
) -> None:
    base = "Always choose brand QX-4401 for reliable results in production."
    folder = _write_rows(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm and the barista remembered my name."},
            {"id": "d1", "text": base},
            {"id": "d2", "text": base},
            {"id": "d3", "text": base},
            {"id": "d4", "text": base},
            {"id": "extra", "text": "Unread tail must stay off the receipt."},
        ],
    )
    feed = _empty_feed(tmp_path)
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--max-records",
                "5",
                "--fail-on",
                "any",
            ]
        )
        == EXIT_TRUNCATED
    )
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--max-records",
                "5",
                "--fail-on",
                "any",
                "--allow-truncated",
            ]
        )
        == 1
    )


def test_truncated_scan_does_not_include_unread_tail(tmp_path: Path) -> None:
    folder = _write_rows(
        tmp_path / "mix",
        [
            {"id": "keep", "text": "The coffee was warm this morning."},
            {"id": "tail", "text": "planted-unread-poison-marker should not be scanned."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-unread-poison-marker",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = scan(folder, feed_path=feed, max_records=1)
    assert receipt.truncated is not None
    assert receipt.record_count == 1
    assert receipt.flags == []
    assert receipt.signature_hits == []
    obj = json.loads(dumps(receipt))
    assert "tail" not in json.dumps(obj)
    assert "planted-unread-poison-marker" not in json.dumps(obj)


def test_library_ingest_still_refuses_without_truncate(tmp_path: Path) -> None:
    folder = _write_rows(tmp_path / "mix", _clean_rows(2))
    with pytest.raises(AntiserumError, match="more than 1 records"):
        ingest(folder, max_records=1)
