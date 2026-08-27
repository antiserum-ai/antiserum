"""Receipt load errors and determinism on a constructed mix (not the toy demo)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.models import PACK_COVERAGE, PACK_NONE, PACK_NONE_COVERAGE
from antiserum.receipt import dumps, format_text, load_json, loads
from antiserum.scan import scan
from antiserum.signatures import identify_pack


def _mixed_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "mix"
    folder.mkdir()
    (folder / "rows.jsonl").write_text(
        '{"id": "a", "text": "alpha row", "label": "pos"}\n'
        '{"id": "b", "text": "beta row"}\n',
        encoding="utf-8",
    )
    (folder / "note.txt").write_text("plain file body\n", encoding="utf-8")
    return folder


def test_constructed_receipt_is_byte_identical(tmp_path: Path) -> None:
    folder = _mixed_folder(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    first = dumps(scan(folder, feed_path=feed))
    second = dumps(scan(folder, feed_path=feed))
    assert first == second
    obj = json.loads(first)
    assert obj["scanner"] == "antiserum"
    assert obj["dataset_hash"].startswith("sha256:")
    assert obj["record_count"] == 3
    assert obj["pack"]["path"] == str(feed)
    assert obj["pack"]["hash"] == "sha256:" + hashlib.sha256(feed.read_bytes()).hexdigest()
    assert obj["pack"]["signature_count"] == 0
    assert obj["pack"]["coverage"] == PACK_COVERAGE
    assert obj["flags"] == sorted(
        obj["flags"], key=lambda f: (f["check"], f["record_id"], f["reason"])
    )


def test_cli_json_receipt_stable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _mixed_folder(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    argv = ["scan", str(folder), "--feed", str(feed), "--json"]
    assert main(argv) == 0
    first = capsys.readouterr().out
    assert main(argv) == 0
    second = capsys.readouterr().out
    assert first == second
    assert first.lstrip().startswith("{")
    assert json.loads(first)["dataset_hash"] == json.loads(second)["dataset_hash"]


def test_load_json_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="receipt not found"):
        load_json(tmp_path / "nope.json")


def test_loads_rejects_non_object() -> None:
    with pytest.raises(AntiserumError, match="JSON object"):
        loads("[]")


def test_loads_rejects_junk() -> None:
    with pytest.raises(AntiserumError, match="invalid JSON"):
        loads("{not json")


def test_loads_rejects_missing_fields() -> None:
    with pytest.raises(AntiserumError, match="missing required field"):
        loads('{"scanner": "antiserum", "version": "0.1.0"}')


def test_pack_identity_is_sha256_of_local_file(tmp_path: Path) -> None:
    folder = _mixed_folder(tmp_path)
    feed = tmp_path / "signatures.jsonl"
    feed.write_text(
        '{"id": "S1", "match": "literal", "pattern": "alpha"}\n'
        "# comment\n"
        '{"id": "S2", "match": "regex", "pattern": "be+ta"}\n',
        encoding="utf-8",
    )
    receipt = scan(folder, feed_path=feed)
    expected_hash = "sha256:" + hashlib.sha256(feed.read_bytes()).hexdigest()
    assert receipt.pack.path == str(feed)
    assert receipt.pack.hash == expected_hash
    assert receipt.pack.signature_count == 2
    assert receipt.pack.coverage == PACK_COVERAGE
    assert "adaptive" in receipt.pack.coverage
    assert "paraphrased" in receipt.pack.coverage

    obj = json.loads(dumps(receipt))
    assert obj["pack"]["path"] == str(feed)
    assert obj["pack"]["hash"] == expected_hash
    assert obj["pack"]["signature_count"] == 2
    assert obj["pack"]["coverage"] == PACK_COVERAGE

    text = format_text(receipt)
    assert f"pack: {feed}" in text
    assert f"pack_hash: {expected_hash}" in text
    assert "signature_count: 2" in text
    assert PACK_COVERAGE in text


def test_same_pack_bytes_same_receipt(tmp_path: Path) -> None:
    folder = _mixed_folder(tmp_path)
    feed = tmp_path / "signatures.jsonl"
    feed.write_text(
        '{"id": "S1", "match": "literal", "pattern": "alpha"}\n',
        encoding="utf-8",
    )
    first = dumps(scan(folder, feed_path=feed))
    second = dumps(scan(folder, feed_path=feed))
    assert first == second


def test_different_pack_bytes_change_receipt(tmp_path: Path) -> None:
    folder = _mixed_folder(tmp_path)
    feed_a = tmp_path / "a.jsonl"
    feed_b = tmp_path / "b.jsonl"
    feed_a.write_text(
        '{"id": "S1", "match": "literal", "pattern": "alpha"}\n',
        encoding="utf-8",
    )
    feed_b.write_text(
        '{"id": "S1", "match": "literal", "pattern": "beta"}\n',
        encoding="utf-8",
    )
    a = json.loads(dumps(scan(folder, feed_path=feed_a)))
    b = json.loads(dumps(scan(folder, feed_path=feed_b)))
    assert a["dataset_hash"] == b["dataset_hash"]
    assert a["pack"]["hash"] != b["pack"]["hash"]
    assert a["pack"]["path"] == str(feed_a)
    assert b["pack"]["path"] == str(feed_b)


def test_missing_feed_is_recorded_as_none(tmp_path: Path) -> None:
    folder = _mixed_folder(tmp_path)
    receipt = scan(folder, feed_path=None)
    assert receipt.pack.path == PACK_NONE
    assert receipt.pack.hash == PACK_NONE
    assert receipt.pack.signature_count == 0
    assert receipt.pack.coverage == PACK_NONE_COVERAGE
    text = format_text(receipt)
    assert "feed: none" in text
    obj = json.loads(dumps(receipt))
    assert obj["pack"]["path"] == PACK_NONE
    assert obj["pack"]["coverage"] == PACK_NONE_COVERAGE


def test_walk_up_miss_is_feed_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _mixed_folder(tmp_path / "mix")
    monkeypatch.delenv("ANTISERUM_FEED", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(folder)]) == 0
    printed = capsys.readouterr().out
    assert "feed: none" in printed
    assert "pack: none" in printed


def test_identify_pack_missing_path_is_none(tmp_path: Path) -> None:
    pack = identify_pack(tmp_path / "nope.jsonl")
    assert pack.path == PACK_NONE
    assert pack.coverage == PACK_NONE_COVERAGE


def test_loads_keeps_legacy_receipt_without_pack() -> None:
    receipt = loads(
        json.dumps(
            {
                "scanner": "antiserum",
                "version": "0.1.0",
                "path": "mix",
                "dataset_hash": "sha256:abc",
                "record_count": 1,
                "flags": [],
                "signature_hits": [],
            }
        )
    )
    assert receipt.pack.path == PACK_NONE
    assert receipt.pack.coverage == PACK_NONE_COVERAGE


def test_loads_rejects_incomplete_pack() -> None:
    with pytest.raises(AntiserumError, match="pack missing required field"):
        loads(
            json.dumps(
                {
                    "scanner": "antiserum",
                    "version": "0.1.0",
                    "path": "mix",
                    "dataset_hash": "sha256:abc",
                    "record_count": 1,
                    "pack": {"path": "feed/signatures.jsonl"},
                }
            )
        )


def test_loads_rejects_non_object_pack() -> None:
    with pytest.raises(AntiserumError, match="pack' must be a JSON object"):
        loads(
            json.dumps(
                {
                    "scanner": "antiserum",
                    "version": "0.1.0",
                    "path": "mix",
                    "dataset_hash": "sha256:abc",
                    "record_count": 1,
                    "pack": "none",
                }
            )
        )


def test_loads_rejects_non_integer_signature_count() -> None:
    with pytest.raises(AntiserumError, match="signature_count"):
        loads(
            json.dumps(
                {
                    "scanner": "antiserum",
                    "version": "0.1.0",
                    "path": "mix",
                    "dataset_hash": "sha256:abc",
                    "record_count": 1,
                    "pack": {
                        "path": "feed/signatures.jsonl",
                        "hash": "sha256:abc",
                        "signature_count": "two",
                        "coverage": PACK_COVERAGE,
                    },
                }
            )
        )
