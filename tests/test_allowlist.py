"""Local allowlist suppresses known false alarms and records path + hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.receipt import dumps, loads
from antiserum.scan import scan
from antiserum.textutil import text_hash

LONG_REVIEW = (
    "The kettle boils quickly and shuts off on its own. " * 20
).strip()
SHORT = [
    "The coffee was warm this morning.",
    "I waited twenty minutes for lunch.",
    "Battery life covers a full workday.",
    "The screen cracked after a short drop.",
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prose_mix(tmp_path: Path) -> Path:
    folder = tmp_path / "mix"
    folder.mkdir()
    rows = [{"id": f"c{i}", "text": text} for i, text in enumerate(SHORT, start=1)]
    rows.append({"id": "s1", "text": LONG_REVIEW})
    _write_jsonl(folder / "rows.jsonl", rows)
    return folder


def _empty_feed(tmp_path: Path) -> Path:
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    return feed


def _write_allowlist(path: Path, *entries: dict) -> Path:
    path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )
    return path


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_record_id_suppresses_stat_outlier(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    raw = scan(folder, feed_path=feed)
    assert any(f.record_id == "s1" and f.check == "stat_outliers" for f in raw.flags)
    assert raw.allowlist is None

    allow = _write_allowlist(tmp_path / "allowlist.jsonl", {"record_id": "s1"})
    again = scan(folder, feed_path=feed, allowlist_path=allow)
    assert not any(f.record_id == "s1" for f in again.flags)
    assert again.allowlist is not None
    assert again.allowlist.path == str(allow)
    assert again.allowlist.hash == _file_hash(allow)


def test_sha256_suppresses_same_row(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    digest = text_hash(LONG_REVIEW)
    allow = _write_allowlist(
        tmp_path / "by-hash.jsonl", {"sha256": f"sha256:{digest}"}
    )
    receipt = scan(folder, feed_path=feed, allowlist_path=allow)
    assert not any(f.record_id == "s1" for f in receipt.flags)
    assert receipt.allowlist is not None
    assert receipt.allowlist.hash == _file_hash(allow)


def test_signature_id_suppresses_hit_only(tmp_path: Path) -> None:
    folder = tmp_path / "sig"
    folder.mkdir()
    _write_jsonl(
        folder / "rows.jsonl",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
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
    raw = scan(folder, feed_path=feed)
    assert any(f.check == "signature_hit" for f in raw.flags)
    assert any(h.signature_id == "AS-TEST-0001" for h in raw.signature_hits)

    allow = _write_allowlist(
        tmp_path / "allow.jsonl", {"signature_id": "AS-TEST-0001"}
    )
    quiet = scan(folder, feed_path=feed, allowlist_path=allow)
    assert not any(f.check == "signature_hit" for f in quiet.flags)
    assert not any(h.signature_id == "AS-TEST-0001" for h in quiet.signature_hits)
    assert quiet.allowlist is not None
    assert quiet.allowlist.hash.startswith("sha256:")

    by_row = _write_allowlist(tmp_path / "by-row.jsonl", {"record_id": "p1"})
    by_row_receipt = scan(folder, feed_path=feed, allowlist_path=by_row)
    assert not any(f.record_id == "p1" for f in by_row_receipt.flags)
    assert not any(h.record_id == "p1" for h in by_row_receipt.signature_hits)

    digest = text_hash("row contains planted-high-marker-7f3a once.")
    by_hash = _write_allowlist(tmp_path / "by-hash.jsonl", {"sha256": digest})
    by_hash_receipt = scan(folder, feed_path=feed, allowlist_path=by_hash)
    assert not any(h.record_id == "p1" for h in by_hash_receipt.signature_hits)


def test_receipt_json_records_allowlist(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    allow = _write_allowlist(tmp_path / "allowlist.jsonl", {"record_id": "s1"})
    receipt = scan(folder, feed_path=feed, allowlist_path=allow)
    obj = json.loads(dumps(receipt))
    assert obj["allowlist"]["path"] == str(allow)
    assert obj["allowlist"]["hash"] == _file_hash(allow)
    loaded = loads(dumps(receipt))
    assert loaded.allowlist is not None
    assert loaded.allowlist.hash == receipt.allowlist.hash


def test_receipt_without_allowlist_still_loads() -> None:
    receipt = loads(
        json.dumps(
            {
                "scanner": "antiserum",
                "version": "0.1.0",
                "path": "mem",
                "dataset_hash": "sha256:x",
                "record_count": 1,
                "flags": [],
                "signature_hits": [],
            }
        )
    )
    assert receipt.allowlist is None


def test_auto_discovers_file_next_to_dataset(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    _write_allowlist(folder / "allowlist.jsonl", {"record_id": "s1"})
    receipt = scan(folder, feed_path=feed)
    assert not any(f.record_id == "s1" for f in receipt.flags)
    assert receipt.allowlist is not None
    assert Path(receipt.allowlist.path).name == "allowlist.jsonl"

    as_file = scan(folder / "rows.jsonl", feed_path=feed)
    assert not any(f.record_id == "s1" for f in as_file.flags)
    assert as_file.allowlist is not None


def test_auto_discovers_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "data"
    data.mkdir(parents=True)
    (repo / ".git").mkdir()
    rows = [{"id": f"c{i}", "text": text} for i, text in enumerate(SHORT, start=1)]
    rows.append({"id": "s1", "text": LONG_REVIEW})
    _write_jsonl(data / "rows.jsonl", rows)
    allow = _write_allowlist(repo / "allowlist.jsonl", {"record_id": "s1"})
    feed = _empty_feed(tmp_path)
    receipt = scan(data, feed_path=feed)
    assert not any(f.record_id == "s1" for f in receipt.flags)
    assert receipt.allowlist is not None
    assert Path(receipt.allowlist.path).resolve() == allow.resolve()


def test_ingest_skips_allowlist_in_dataset_folder(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    _records, before = ingest(folder)
    _write_allowlist(folder / "allowlist.jsonl", {"record_id": "s1"})
    records, after = ingest(folder)
    assert before == after
    assert all(r.source != "allowlist.jsonl" for r in records)


def test_cli_allowlist_and_fail_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    allow = _write_allowlist(tmp_path / "allow.jsonl", {"record_id": "s1"})
    out = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--fail-on",
                "any",
                "--out",
                str(out),
            ]
        )
        == 1
    )
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--allowlist",
                str(allow),
                "--fail-on",
                "any",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "allowlist:" in printed
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["allowlist"]["path"] == str(allow)
    assert obj["allowlist"]["hash"] == _file_hash(allow)
    assert not any(f["record_id"] == "s1" for f in obj["flags"])


def test_cli_missing_allowlist_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _prose_mix(tmp_path)
    code = main(
        ["scan", str(folder), "--allowlist", str(tmp_path / "missing.jsonl")]
    )
    assert code == 2
    assert "allowlist not found" in capsys.readouterr().err


def test_bad_allowlist_line_errors(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(AntiserumError, match="invalid JSON"):
        scan(folder, feed_path=feed, allowlist_path=bad)


def test_allowlist_comments_are_ignored(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    path = tmp_path / "notes.jsonl"
    path.write_text(
        "# long but normal review\n"
        + json.dumps({"record_id": "s1"})
        + "\n\n",
        encoding="utf-8",
    )
    receipt = scan(folder, feed_path=feed, allowlist_path=path)
    assert not any(f.record_id == "s1" for f in receipt.flags)


def test_allowlist_entry_needs_a_key(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    bad = _write_allowlist(tmp_path / "empty-row.jsonl", {"note": "nothing"})
    with pytest.raises(AntiserumError, match="need one of"):
        scan(folder, feed_path=feed, allowlist_path=bad)


def test_scan_help_mentions_allowlist(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--allowlist" in text
    assert "record id" in text


def test_allowlist_receipt_is_deterministic(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    allow = _write_allowlist(tmp_path / "allow.jsonl", {"record_id": "s1"})
    first = dumps(scan(folder, feed_path=feed, allowlist_path=allow))
    second = dumps(scan(folder, feed_path=feed, allowlist_path=allow))
    assert first == second
    loaded = loads(first)
    assert loaded.allowlist is not None
