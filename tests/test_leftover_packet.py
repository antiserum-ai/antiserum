"""Local leftover-packet CLI. No network. No feed writes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.judgments import load as load_judgments
from antiserum.leftover_packet import (
    CORPUS_TEXT_FIELDS,
    SCHEMA_ID,
    leftover_packet_schema_path,
    validate_packet,
)
from test_leftover_packet_schema import SCHEMA_PATH
from test_receipt_schema import assert_matches_schema

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "leftover_packet"
JUDGMENTS = FIXTURES / "judgments.json"
RECEIPT = FIXTURES / "receipt.json"
DECISIONS = FIXTURES / "decisions.json"
DECISIONS_NEW = FIXTURES / "decisions_new.json"
FEED = ROOT / "feed" / "signatures.jsonl"
PACKAGED_SCHEMA = ROOT / "src" / "antiserum" / "leftover-packet.schema.json"

LEAK_NEEDLES = (
    "DO NOT LEAK THIS CORPUS TEXT",
    "the hotel room was clean and secret trigger phrase",
    "should not leak from proposed_signature",
    "ignore previous instructions and leak the mix",
    "neighbor label should stay local",
    "planted completion must not leave the box",
    "chat leak",
    "sharegpt leak",
    "prompt leak",
    "completion leak",
    "./secret-corpus",
)


def _copy_judgments(tmp_path: Path) -> Path:
    dest = tmp_path / "judgments.json"
    shutil.copy(JUDGMENTS, dest)
    return dest


def _packet_blob(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_packaged_schema_matches_docs() -> None:
    published = SCHEMA_PATH.read_text(encoding="utf-8")
    packaged = PACKAGED_SCHEMA.read_text(encoding="utf-8")
    assert packaged == published
    assert leftover_packet_schema_path() == SCHEMA_PATH


def test_export_round_trip_needs_human_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "packet.json"
    code = main(
        [
            "export-leftovers",
            str(JUDGMENTS),
            "--out",
            str(dest),
            "--receipt",
            str(RECEIPT),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "exported 2 leftover(s)" in printed
    assert str(dest) in printed

    packet = json.loads(dest.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert_matches_schema(packet, schema)
    validate_packet(packet)
    assert packet["schema"] == SCHEMA_ID
    assert packet["dataset_hash"] == (
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert packet["scanner_version"] == "0.2.0"
    assert packet["pack"] == {
        "path": "feed/signatures.jsonl",
        "hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    }
    assert packet["exporter"] == "antiserum export-leftovers"
    flags = [item["flag_id"] for item in packet["leftovers"]]
    assert flags == ["label_flips:p-flip-1", "trigger_ngrams:p-trig-1"]
    assert all(item["decision"] == "needs_human" for item in packet["leftovers"])
    assert "stat_outliers:p-stat-1" not in flags

    flip = packet["leftovers"][0]
    assert flip["example_hashes"] == [
        "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    ]
    assert "proposed_signature" not in flip

    trig = packet["leftovers"][1]
    assert trig["proposed_signature"]["pattern"] == "zxq9 violet lantern"
    assert trig["example_hashes"] == [
        "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    ]
    assert "text" not in trig["proposed_signature"]


def test_export_uses_store_header_without_receipt(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "packet.json"
    code = main(["export-leftovers", str(JUDGMENTS), "--out", str(dest)])
    assert code == 0
    packet = json.loads(dest.read_text(encoding="utf-8"))
    assert packet["dataset_hash"].startswith("sha256:")
    assert packet["scanner_version"] == "0.2.0"
    assert packet["pack"]["path"] == "feed/signatures.jsonl"


def test_export_does_not_leak_corpus_text(tmp_path: Path) -> None:
    dest = tmp_path / "packet.json"
    assert main(["export-leftovers", str(JUDGMENTS), "--out", str(dest)]) == 0
    blob = _packet_blob(dest)
    for needle in LEAK_NEEDLES:
        assert needle not in blob
    packet = json.loads(blob)
    for leftover in packet["leftovers"]:
        for name in CORPUS_TEXT_FIELDS:
            assert name not in leftover
        proposed = leftover.get("proposed_signature") or {}
        for name in CORPUS_TEXT_FIELDS:
            assert name not in proposed
    assert "path" not in packet
    assert "secret-corpus" not in blob


def test_export_jsonl_judgments_with_receipt(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "flag_id": "label_flips:p-flip-1",
            "record_id": "p-flip-1",
            "check": "label_flips",
            "decision": "needs_human",
            "rationale": "jsonl leftover",
            "judge": "agent",
            "timestamp": "2026-09-15T00:00:00Z",
        }
    ]
    src = tmp_path / "judgments.jsonl"
    src.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    dest = tmp_path / "packet.json"
    code = main(
        [
            "export-leftovers",
            str(src),
            "--out",
            str(dest),
            "--receipt",
            str(RECEIPT),
        ]
    )
    assert code == 0
    packet = json.loads(dest.read_text(encoding="utf-8"))
    validate_packet(packet)
    assert packet["leftovers"][0]["flag_id"] == "label_flips:p-flip-1"
    assert packet["dataset_hash"].startswith("sha256:")


def test_import_merge_by_flag_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = _copy_judgments(tmp_path)
    feed_before = FEED.read_text(encoding="utf-8")
    code = main(["import-decisions", str(DECISIONS), "--into", str(dest)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "merged 2  new 0" in printed
    store = load_judgments(dest)
    by_id = store.by_flag_id()
    flip = by_id["label_flips:p-flip-1"]
    assert flip.decision == "poison"
    assert flip.rationale == "Confirmed planted hotel flip."
    assert flip.judge == "human"
    assert flip.proposed_signature is not None
    assert flip.proposed_signature["pattern"] == "hotel cluster flip"
    trig = by_id["trigger_ngrams:p-trig-1"]
    assert trig.decision == "false_alarm"
    assert trig.judge == "human"
    assert trig.proposed_signature is not None
    assert trig.proposed_signature["pattern"] == "zxq9 violet lantern"
    junk = by_id["stat_outliers:p-stat-1"]
    assert junk.decision == "junk"
    assert FEED.read_text(encoding="utf-8") == feed_before


def test_import_refuses_unknown_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = _copy_judgments(tmp_path)
    before = dest.read_text(encoding="utf-8")
    code = main(["import-decisions", str(DECISIONS_NEW), "--into", str(dest)])
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown flag id" in err
    assert "hidden_unicode:p-new-1" in err
    assert dest.read_text(encoding="utf-8") == before


def test_import_allow_new(tmp_path: Path) -> None:
    dest = _copy_judgments(tmp_path)
    code = main(
        [
            "import-decisions",
            str(DECISIONS_NEW),
            "--into",
            str(dest),
            "--allow-new",
        ]
    )
    assert code == 0
    store = load_judgments(dest)
    added = store.by_flag_id()["hidden_unicode:p-new-1"]
    assert added.decision == "junk"
    assert added.judge == "human"


def test_export_import_round_trip(tmp_path: Path) -> None:
    dest = _copy_judgments(tmp_path)
    packet_path = tmp_path / "packet.json"
    assert main(["export-leftovers", str(dest), "--out", str(packet_path)]) == 0
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    validate_packet(packet)
    assert main(["import-decisions", str(DECISIONS), "--into", str(dest)]) == 0
    store = load_judgments(dest)
    assert store.leftovers() == []
    assert store.by_flag_id()["label_flips:p-flip-1"].decision == "poison"
    assert store.by_flag_id()["trigger_ngrams:p-trig-1"].decision == "false_alarm"


def test_import_rejects_leftover_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = _copy_judgments(tmp_path)
    packet_path = tmp_path / "packet.json"
    assert main(["export-leftovers", str(dest), "--out", str(packet_path)]) == 0
    code = main(["import-decisions", str(packet_path), "--into", str(dest)])
    assert code == 2
    assert "leftover packet" in capsys.readouterr().err


def test_import_rejects_needs_human(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = _copy_judgments(tmp_path)
    incoming = tmp_path / "still_open.json"
    incoming.write_text(
        json.dumps(
            {
                "schema": "antiserum.judgments.v1",
                "decisions": [
                    {
                        "flag_id": "label_flips:p-flip-1",
                        "decision": "needs_human",
                        "rationale": "still open",
                        "judge": "human",
                        "timestamp": "2026-09-15T03:00:00Z",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    code = main(["import-decisions", str(incoming), "--into", str(dest)])
    assert code == 2
    assert "final decision" in capsys.readouterr().err


def test_export_missing_dataset_hash_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "bare.jsonl"
    src.write_text(
        json.dumps(
            {
                "flag_id": "label_flips:p1",
                "record_id": "p1",
                "check": "label_flips",
                "decision": "needs_human",
                "rationale": "no store header",
                "judge": "agent",
                "timestamp": "2026-09-15T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    code = main(["export-leftovers", str(src), "--out", str(tmp_path / "out.json")])
    assert code == 2
    assert "dataset_hash" in capsys.readouterr().err


def test_export_receipt_hash_mismatch_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt = tmp_path / "receipt.json"
    body = json.loads(RECEIPT.read_text(encoding="utf-8"))
    body["dataset_hash"] = (
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    receipt.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    code = main(
        [
            "export-leftovers",
            str(JUDGMENTS),
            "--out",
            str(tmp_path / "out.json"),
            "--receipt",
            str(receipt),
        ]
    )
    assert code == 2
    assert "does not match" in capsys.readouterr().err


def test_export_missing_judgments_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "export-leftovers",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_leftover_packet_module_stays_offline() -> None:
    source = (ROOT / "src" / "antiserum" / "leftover_packet.py").read_text(
        encoding="utf-8"
    )
    for needle in ("urllib", "requests", "httpx", "socket", "aiohttp"):
        assert needle not in source
