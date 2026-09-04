"""Local allowlist suppresses known false alarms and records path + hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from antiserum.allowlist import (
    append_entries,
    collect_false_alarm_entries,
    resolve_allowlist_dest,
)
from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.judgments import Judgment, JudgmentStore
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


def _false_alarm_store(*record_ids: str) -> JudgmentStore:
    judgments = [
        Judgment(
            flag_id=f"stat_outliers:{rid}",
            record_id=rid,
            check="stat_outliers",
            decision="false_alarm",
            rationale="long but normal review",
            judge="human",
            timestamp="2026-09-04T00:00:00Z",
        )
        for rid in record_ids
    ]
    return JudgmentStore(path="mem", dataset_hash="sha256:x", judgments=judgments)


def test_collect_false_alarms_uses_record_id_and_hash(tmp_path: Path) -> None:
    folder = _prose_mix(tmp_path)
    records, _digest = ingest(folder)
    store = JudgmentStore(
        path=str(folder),
        dataset_hash="sha256:x",
        judgments=[
            Judgment(
                flag_id="stat_outliers:s1",
                record_id="s1",
                check="stat_outliers",
                decision="false_alarm",
                rationale="long but normal review",
                judge="agent",
                timestamp="2026-09-04T00:00:00Z",
            ),
            Judgment(
                flag_id="stat_outliers:s1-dup",
                record_id="s1",
                check="stat_outliers",
                decision="false_alarm",
                rationale="same row, second check",
                judge="human",
                timestamp="2026-09-04T00:00:01Z",
            ),
            Judgment(
                flag_id="duplicate_inject:p1",
                record_id="p1",
                check="duplicate_inject",
                decision="poison",
                rationale="plant",
                judge="agent",
                timestamp="2026-09-04T00:00:00Z",
            ),
            Judgment(
                flag_id="label_flips:p2",
                record_id="p2",
                check="label_flips",
                decision="needs_human",
                rationale="leftover",
                judge="agent",
                timestamp="2026-09-04T00:00:00Z",
            ),
        ],
    )
    entries = collect_false_alarm_entries(store, records)
    assert entries == [{"record_id": "s1", "sha256": text_hash(LONG_REVIEW)}]


def test_collect_false_alarms_record_id_only_without_records() -> None:
    store = _false_alarm_store("s1")
    assert collect_false_alarm_entries(store) == [{"record_id": "s1"}]


def test_append_entries_is_idempotent(tmp_path: Path) -> None:
    dest = tmp_path / "allowlist.jsonl"
    dest.write_text("# keep this comment\n", encoding="utf-8")
    first_added, first_skipped = append_entries(
        dest, [{"record_id": "s1", "sha256": "abc"}]
    )
    assert first_added == 1
    assert first_skipped == 0
    body = dest.read_text(encoding="utf-8")
    assert body.startswith("# keep this comment\n")
    assert body.count('"record_id":"s1"') == 1
    again_added, again_skipped = append_entries(
        dest, [{"record_id": "s1", "sha256": "abc"}]
    )
    assert again_added == 0
    assert again_skipped == 1
    assert dest.read_text(encoding="utf-8") == body


def test_append_skips_existing_record_id_or_hash(tmp_path: Path) -> None:
    dest = _write_allowlist(tmp_path / "allowlist.jsonl", {"record_id": "s1"})
    added, skipped = append_entries(
        dest, [{"record_id": "s1", "sha256": "deadbeef"}]
    )
    assert added == 0
    assert skipped == 1
    hashed = _write_allowlist(tmp_path / "by-hash.jsonl", {"sha256": "abc"})
    added, skipped = append_entries(
        hashed, [{"record_id": "s2", "sha256": "abc"}]
    )
    assert added == 0
    assert skipped == 1


def test_resolve_allowlist_dest_creates_next_to_dataset(tmp_path: Path) -> None:
    folder = tmp_path / "mix"
    folder.mkdir()
    dest = resolve_allowlist_dest(None, folder)
    assert dest == folder / "allowlist.jsonl"
    explicit = tmp_path / "custom.jsonl"
    assert resolve_allowlist_dest(explicit, folder) == explicit


def test_cli_allowlist_add_then_scan_stays_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _prose_mix(tmp_path)
    feed = _empty_feed(tmp_path)
    judgments = tmp_path / "judgments.json"
    allow = tmp_path / "allowlist.jsonl"
    receipt = tmp_path / "receipt.json"

    raw = scan(folder, feed_path=feed)
    assert any(f.record_id == "s1" and f.check == "stat_outliers" for f in raw.flags)
    assert raw.allowlist is None

    assert (
        main(
            [
                "judge",
                str(folder),
                "--feed",
                str(feed),
                "--out",
                str(judgments),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "allowlist",
                "add",
                "--judgments",
                str(judgments),
                "--path",
                str(folder),
                "--out",
                str(allow),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "appended 1 line(s)" in printed
    assert str(allow) in printed
    line = json.loads(allow.read_text(encoding="utf-8").splitlines()[0])
    assert line["record_id"] == "s1"
    assert line["sha256"] == text_hash(LONG_REVIEW)

    assert (
        main(
            [
                "allowlist",
                "add",
                "--judgments",
                str(judgments),
                "--path",
                str(folder),
                "--out",
                str(allow),
            ]
        )
        == 0
    )
    again = capsys.readouterr().out
    assert "appended 0 line(s)" in again
    assert "skipped 1 already listed" in again
    assert allow.read_text(encoding="utf-8").count("\n") == 1

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
                str(receipt),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "allowlist:" in printed
    assert str(allow) in printed
    obj = json.loads(receipt.read_text(encoding="utf-8"))
    assert obj["allowlist"]["path"] == str(allow)
    assert obj["allowlist"]["hash"] == _file_hash(allow)
    assert not any(f["record_id"] == "s1" for f in obj["flags"])


def test_cli_allowlist_add_no_false_alarms(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "judgments.json"
    dest.write_text(
        json.dumps(
            {
                "schema": "antiserum.judgments.v1",
                "path": "mem",
                "dataset_hash": "sha256:x",
                "judgments": [
                    {
                        "flag_id": "duplicate_inject:p1",
                        "record_id": "p1",
                        "check": "duplicate_inject",
                        "decision": "poison",
                        "rationale": "plant",
                        "judge": "agent",
                        "timestamp": "2026-09-04T00:00:00Z",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    allow = tmp_path / "allowlist.jsonl"
    assert (
        main(
            [
                "allowlist",
                "add",
                "--judgments",
                str(dest),
                "--out",
                str(allow),
            ]
        )
        == 0
    )
    assert "no false_alarm judgments to add" in capsys.readouterr().out
    assert not allow.exists()
