"""Receipt load errors and determinism on a constructed mix (not the toy demo)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.receipt import dumps, load_json, loads
from antiserum.scan import scan


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
