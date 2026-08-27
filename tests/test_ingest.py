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


def test_unknown_shape_names_one_line_fix(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x", "label": "pos"}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="unknown row shape"):
        ingest(path)
    with pytest.raises(AntiserumError, match="add a string 'text' field"):
        ingest(path)


def test_text_wins_over_other_shapes(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(
        '{"id": "t", "text": "keep me", "instruction": "ignore", "output": "nope"}\n',
        encoding="utf-8",
    )
    records, _digest = ingest(path)
    assert records[0].text == "keep me"


def test_incomplete_prompt_completion_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"prompt": "only prompt"}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="missing 'completion'"):
        ingest(path)


def test_messages_need_content_or_value(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"messages": [{"role": "user"}]}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="content' or 'value'"):
        ingest(path)


def test_common_sft_shapes(tmp_path: Path) -> None:
    path = tmp_path / "sft.jsonl"
    path.write_text(
        '{"id": "alpaca", "instruction": "Say hi", "input": "to the room", "output": "hello"}\n'
        '{"id": "sharegpt", "conversations": [{"from": "human", "value": "Hi"}, {"from": "gpt", "value": "Hello"}]}\n'
        '{"id": "messages", "messages": [{"role": "user", "content": "Ping"}, {"role": "assistant", "content": "Pong"}]}\n'
        '{"id": "hf", "prompt": "Q: 2+2?", "completion": "A: 4"}\n',
        encoding="utf-8",
    )
    records, _digest = ingest(path)
    by_id = {r.id: r.text for r in records}
    assert by_id["alpaca"] == "Say hi\n\nto the room\n\nhello"
    assert by_id["sharegpt"] == "Hi\n\nHello"
    assert by_id["messages"] == "Ping\n\nPong"
    assert by_id["hf"] == "Q: 2+2?\n\nA: 4"


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


def test_nested_txt_and_jsonl_hash_tracks_both(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "rows.jsonl").write_text(
        '{"id": "a", "text": "hello from jsonl"}\n',
        encoding="utf-8",
    )
    (tmp_path / "sub" / "note.txt").write_text("plain nested file\n", encoding="utf-8")
    records, digest = ingest(tmp_path)
    assert {r.id for r in records} == {"a", "note"}
    assert {r.source for r in records} == {"rows.jsonl", "sub/note.txt"}
    (tmp_path / "sub" / "note.txt").write_text("plain nested file changed\n", encoding="utf-8")
    _records, changed = ingest(tmp_path)
    assert digest != changed
    (tmp_path / "rows.jsonl").write_text(
        '{"id": "a", "text": "hello from jsonl"}\n'
        '{"id": "b", "text": "second"}\n',
        encoding="utf-8",
    )
    _records, changed_jsonl = ingest(tmp_path)
    assert changed_jsonl != changed


def test_empty_jsonl_with_txt_still_loads(tmp_path: Path) -> None:
    (tmp_path / "empty.jsonl").write_text("\n\n", encoding="utf-8")
    (tmp_path / "note.txt").write_text("only the text file\n", encoding="utf-8")
    records, digest = ingest(tmp_path)
    assert [r.id for r in records] == ["note"]
    assert digest.startswith("sha256:")


def test_empty_jsonl_file_errors(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(AntiserumError, match="no text records"):
        ingest(path)
