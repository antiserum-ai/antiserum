import inspect
import json
from pathlib import Path

import pytest

from antiserum.errors import AntiserumError
from antiserum.ingest import DEFAULT_MAX_BYTES, DEFAULT_MAX_RECORDS, ingest


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
    with pytest.raises(
        AntiserumError, match="no \\.jsonl, \\.json, \\.csv, \\.txt, \\.arrow, or \\.parquet"
    ):
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


def test_txt_record_limit_counts_each_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("first file\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("second file\n", encoding="utf-8")
    with pytest.raises(AntiserumError, match="more than 1 records"):
        ingest(tmp_path, max_records=1)
    records, _digest = ingest(tmp_path, max_records=2)
    assert {r.id for r in records} == {"a", "b"}


def test_record_limit_fails_instead_of_loading_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(
        '{"id": "a", "text": "one"}\n'
        '{"id": "b", "text": "two"}\n'
        '{"id": "c", "text": "three"}\n',
        encoding="utf-8",
    )
    with pytest.raises(AntiserumError, match="more than 2 records"):
        ingest(path, max_records=2)
    with pytest.raises(AntiserumError, match="O\\(n²\\) Jaccard"):
        ingest(path, max_records=2)
    records, _digest = ingest(path, max_records=3)
    assert [r.id for r in records] == ["a", "b", "c"]


def test_byte_limit_fails_before_parse(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    body = '{"id": "a", "text": "hello"}\n'
    path.write_text(body, encoding="utf-8")
    size = path.stat().st_size
    with pytest.raises(AntiserumError, match=f"{size} bytes on disk"):
        ingest(path, max_bytes=size - 1)
    records, _digest = ingest(path, max_bytes=size)
    assert [r.id for r in records] == ["a"]


def test_limits_do_not_change_dataset_hash(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text('{"id": "1", "text": "abc"}\n', encoding="utf-8")
    _records, default = ingest(tmp_path)
    _records, raised = ingest(tmp_path, max_records=100, max_bytes=10_000)
    assert default == raised
    assert default.startswith("sha256:")


def test_invalid_limits(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text('{"id": "1", "text": "abc"}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="max_records must be at least 1"):
        ingest(tmp_path, max_records=0)
    with pytest.raises(AntiserumError, match="max_bytes must be at least 1"):
        ingest(tmp_path, max_bytes=0)


def test_jsonl_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b'{"id": "x", "text": "hello \xff"}\n')
    with pytest.raises(AntiserumError, match="not valid UTF-8"):
        ingest(path)


def test_default_ceiling_is_documented() -> None:
    assert DEFAULT_MAX_RECORDS == 25_000
    assert DEFAULT_MAX_BYTES == 128 * 1024 * 1024


def test_csv_and_json_array_accepted_shapes(tmp_path: Path) -> None:
    (tmp_path / "text.csv").write_text(
        "id,text,label\ncsv-text,plain text row,pos\n",
        encoding="utf-8",
    )
    (tmp_path / "alpaca.csv").write_text(
        "id,instruction,input,output\n"
        "csv-alpaca,Say hi,to the room,hello\n",
        encoding="utf-8",
    )
    (tmp_path / "hf.csv").write_text(
        "id,prompt,completion\ncsv-hf,Q: 2+2?,A: 4\n",
        encoding="utf-8",
    )
    (tmp_path / "text.json").write_text(
        json.dumps([{"id": "json-text", "text": "plain text row", "label": "pos"}]),
        encoding="utf-8",
    )
    (tmp_path / "alpaca.json").write_text(
        json.dumps(
            [
                {
                    "id": "json-alpaca",
                    "instruction": "Say hi",
                    "input": "to the room",
                    "output": "hello",
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "hf.json").write_text(
        json.dumps([{"id": "json-hf", "prompt": "Q: 2+2?", "completion": "A: 4"}]),
        encoding="utf-8",
    )
    records, _digest = ingest(tmp_path)
    by_id = {r.id: r.text for r in records}
    assert by_id["csv-text"] == "plain text row"
    assert by_id["json-text"] == "plain text row"
    assert by_id["csv-alpaca"] == "Say hi\n\nto the room\n\nhello"
    assert by_id["json-alpaca"] == "Say hi\n\nto the room\n\nhello"
    assert by_id["csv-hf"] == "Q: 2+2?\n\nA: 4"
    assert by_id["json-hf"] == "Q: 2+2?\n\nA: 4"


def test_csv_unknown_header_names_one_line_fix(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("question,answer\nWhat?,42\n", encoding="utf-8")
    with pytest.raises(AntiserumError, match="unknown CSV header"):
        ingest(path)
    with pytest.raises(AntiserumError, match="add a string 'text' field"):
        ingest(path)


def test_json_array_unknown_shape_names_one_line_fix(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('[{"id": "x", "label": "pos"}]\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="unknown row shape"):
        ingest(path)
    with pytest.raises(AntiserumError, match="add a string 'text' field"):
        ingest(path)


def test_json_object_is_not_an_array(tmp_path: Path) -> None:
    path = tmp_path / "one.json"
    path.write_text('{"id": "x", "text": "only"}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="expected a JSON array of objects"):
        ingest(path)


def test_jsonl_inside_json_suffix_fails(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text(
        '{"id": "a", "text": "one"}\n{"id": "b", "text": "two"}\n',
        encoding="utf-8",
    )
    with pytest.raises(AntiserumError, match="one JSON array of objects"):
        ingest(path)


def test_reference_sidecar_json_is_not_ingested(tmp_path: Path) -> None:
    (tmp_path / "rows.jsonl").write_text(
        '{"id": "a", "text": "keep"}\n', encoding="utf-8"
    )
    (tmp_path / "manifest.json").write_text('{"plants": []}\n', encoding="utf-8")
    (tmp_path / "thresholds.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "eval.json").write_text("{}\n", encoding="utf-8")
    records, _digest = ingest(tmp_path)
    assert [r.id for r in records] == ["a"]
    assert [r.source for r in records] == ["rows.jsonl"]


def test_csv_record_limit(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("id,text\na,one\nb,two\nc,three\n", encoding="utf-8")
    with pytest.raises(AntiserumError, match="more than 2 records"):
        ingest(path, max_records=2)
    records, _digest = ingest(path, max_records=3)
    assert [r.id for r in records] == ["a", "b", "c"]


def test_ingest_module_does_not_import_pandas() -> None:
    import antiserum.ingest as ingest_mod

    src = inspect.getsource(ingest_mod)
    assert "import pandas" not in src
    assert "from pandas" not in src
    assert "import csv" in src
    assert "import json" in src
