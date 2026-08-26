from pathlib import Path

import pytest

from antiserum.errors import AntiserumError
from antiserum.ingest import ingest


def test_jsonl_and_txt(tmp_path: Path) -> None:
    (tmp_path / "rows.jsonl").write_text(
        '{"id": "a", "text": "hello", "label": "pos"}\n'
        '{"text": "no id here"}\n',
        encoding="utf-8",
    )
    (tmp_path / "note.txt").write_text("plain file\n", encoding="utf-8")
    records, digest = ingest(tmp_path)
    ids = {r.id for r in records}
    assert ids == {"a", "rows.jsonl:2", "note"}
    assert digest.startswith("sha256:")
    labels = {r.id: r.label for r in records}
    assert labels["a"] == "pos"
    assert labels["rows.jsonl:2"] is None


def test_single_jsonl_file(tmp_path: Path) -> None:
    path = tmp_path / "one.jsonl"
    path.write_text('{"id": "x", "text": "only"}\n', encoding="utf-8")
    records, _digest = ingest(path)
    assert [r.id for r in records] == ["x"]


def test_missing_path(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="does not exist"):
        ingest(tmp_path / "missing")


def test_empty_folder(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="no \\.jsonl or \\.txt"):
        ingest(tmp_path)


def test_unsupported_file(tmp_path: Path) -> None:
    path = tmp_path / "model.bin"
    path.write_bytes(b"\x00\x01")
    with pytest.raises(AntiserumError, match="unsupported file type"):
        ingest(path)


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "ok", "text": "fine"}\n{not json\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="invalid JSON"):
        ingest(path)


def test_missing_text(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x", "label": "pos"}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="missing required field 'text'"):
        ingest(path)


def test_text_not_string(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x", "text": ["nope"]}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="must be a string"):
        ingest(path)


def test_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_bytes(b"hello \xff world")
    with pytest.raises(AntiserumError, match="not valid UTF-8"):
        ingest(path)


def test_hash_stable_for_same_bytes(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text('{"id": "1", "text": "abc"}\n', encoding="utf-8")
    _records, first = ingest(tmp_path)
    _records, second = ingest(tmp_path)
    assert first == second
