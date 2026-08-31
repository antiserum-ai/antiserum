"""Local Hugging Face cache scan. Fixture dirs only — no network."""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum import hf_local
from antiserum.hf_local import (
    default_datasets_cache,
    empty_cache_error,
    looks_like_hf_dir,
    looks_like_hf_path,
    missing_cache_error,
    read_rows,
)
from antiserum.ingest import ingest
from antiserum.scan import scan

REPO = Path(__file__).resolve().parents[1]
HF_CACHE = REPO / "tests" / "fixtures" / "hf_cache"
HF_SAVED = REPO / "tests" / "fixtures" / "hf_saved"


def test_scan_datasets_cache_fixture_writes_receipt(
    feed_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "receipt.json"
    code = main(
        ["scan", str(HF_CACHE), "--feed", str(feed_path), "--out", str(out)]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "dataset_hash: sha256:" in printed
    assert "records: 2" in printed
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["record_count"] == 2
    assert body["dataset_hash"].startswith("sha256:")


def test_ingest_datasets_cache_fixture() -> None:
    records, digest = ingest(HF_CACHE)
    by_id = {r.id: r for r in records}
    assert set(by_id) == {"hf-1", "hf-2"}
    assert by_id["hf-1"].text == "a clean local cache row"
    assert by_id["hf-1"].label == "pos"
    assert by_id["hf-2"].label == "neg"
    assert digest.startswith("sha256:")
    assert "dataset_info.json" not in {r.source for r in records}


def test_ingest_save_to_disk_fixture() -> None:
    records, digest = ingest(HF_SAVED)
    assert {r.id for r in records} == {"saved-1", "saved-2"}
    assert records[0].text.startswith("already-downloaded")
    assert digest.startswith("sha256:")
    sources = {r.source for r in records}
    assert "train/train.jsonl" in sources
    assert "dataset_info.json" not in sources
    assert "dataset_dict.json" not in sources
    assert "state.json" not in sources


def test_scan_save_to_disk_fixture_receipt(feed_path: Path) -> None:
    receipt = scan(HF_SAVED, feed_path=feed_path)
    assert receipt.record_count == 2
    assert receipt.dataset_hash.startswith("sha256:")
    assert receipt.path == str(HF_SAVED)


def test_missing_hf_cache_tells_them_to_fetch(tmp_path: Path) -> None:
    missing = tmp_path / ".cache" / "huggingface" / "datasets" / "nope"
    with pytest.raises(AntiserumError, match="Fetch the dataset yourself"):
        ingest(missing)
    with pytest.raises(AntiserumError, match="does not download"):
        ingest(missing)


def test_missing_regular_path_is_unchanged(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="does not exist"):
        ingest(tmp_path / "nope")


def test_empty_hf_cache_dir_tells_them_to_fetch(tmp_path: Path) -> None:
    cache = tmp_path / "huggingface" / "datasets"
    cache.mkdir(parents=True)
    with pytest.raises(AntiserumError, match="Fetch the dataset yourself"):
        ingest(cache)


def test_empty_hf_cache_with_only_metadata(tmp_path: Path) -> None:
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "dataset_info.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AntiserumError, match="Fetch the dataset yourself"):
        ingest(folder)


def test_cli_missing_hf_cache_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "huggingface" / "datasets" / "missing"
    code = main(["scan", str(missing)])
    assert code == 2
    err = capsys.readouterr().err
    assert "Fetch the dataset yourself" in err
    assert "does not download" in err


def test_scan_help_mentions_local_hf_cache(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "Hugging Face" in printed
    assert "Does not download" in printed


def test_ingest_does_not_import_hub_or_datasets() -> None:
    banned = ("huggingface_hub", "datasets")
    before = {name for name in banned if name in sys.modules}
    ingest(HF_CACHE)
    ingest(HF_SAVED)
    after = {name for name in banned if name in sys.modules}
    assert after == before


def test_ingest_module_does_not_import_pyarrow() -> None:
    import antiserum.ingest as ingest_mod
    import antiserum.hf_local as hf_mod

    ingest_src = inspect.getsource(ingest_mod)
    hf_src = inspect.getsource(hf_mod)
    assert "import pyarrow" not in ingest_src
    assert "import huggingface_hub" not in ingest_src
    assert "import huggingface_hub" not in hf_src
    assert "from huggingface_hub" not in hf_src
    load_src = inspect.getsource(hf_mod._load_pyarrow)
    assert "import pyarrow" in load_src


def test_arrow_file_without_pyarrow(tmp_path: Path) -> None:
    path = tmp_path / "rows.arrow"
    path.write_bytes(b"ARROW1\x00\x00")
    with pytest.raises(AntiserumError, match="pip install 'antiserum\\[hf\\]'"):
        ingest(path)
    with pytest.raises(AntiserumError, match="does not download"):
        ingest(path)


def test_parquet_file_without_pyarrow(tmp_path: Path) -> None:
    path = tmp_path / "rows.parquet"
    path.write_bytes(b"PAR1")
    with pytest.raises(AntiserumError, match="optional extra"):
        ingest(path)


def test_read_rows_uses_local_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "rows.arrow"
    path.write_bytes(b"fake")

    class FakeTable:
        def to_pylist(self) -> list[dict]:
            return [
                {"id": "a", "text": "from arrow", "label": "pos"},
                {"id": "b", "text": "second arrow row"},
            ]

    monkeypatch.setattr("antiserum.hf_local._read_table", lambda _p: FakeTable())
    rows = read_rows(path)
    assert rows[0]["text"] == "from arrow"
    records, _digest = ingest(path)
    assert [r.id for r in records] == ["a", "b"]
    assert records[0].text == "from arrow"
    assert records[0].label == "pos"


def test_read_rows_rejects_non_object(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "rows.arrow"
    path.write_bytes(b"fake")

    class FakeTable:
        def to_pylist(self) -> list[object]:
            return ["not a row"]

    monkeypatch.setattr("antiserum.hf_local._read_table", lambda _p: FakeTable())
    with pytest.raises(AntiserumError, match="expected an object"):
        read_rows(path)


def test_looks_like_hf_path_and_dir(tmp_path: Path) -> None:
    assert looks_like_hf_path(Path("/home/me/.cache/huggingface/datasets"))
    assert looks_like_hf_path(tmp_path / "rows.arrow")
    assert not looks_like_hf_path(tmp_path / "plain")
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "dataset_dict.json").write_text("{}", encoding="utf-8")
    assert looks_like_hf_dir(saved)
    split = tmp_path / "split"
    split.mkdir()
    (split / "train").mkdir()
    (split / "train" / "dataset_info.json").write_text("{}", encoding="utf-8")
    assert looks_like_hf_dir(split)


def test_default_datasets_cache_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_DATASETS_CACHE", str(tmp_path / "custom"))
    assert default_datasets_cache() == tmp_path / "custom"
    monkeypatch.delenv("HF_DATASETS_CACHE")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hfhome"))
    assert default_datasets_cache() == tmp_path / "hfhome" / "datasets"
    monkeypatch.delenv("HF_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_datasets_cache() == tmp_path / ".cache" / "huggingface" / "datasets"


def test_missing_and_empty_error_text() -> None:
    path = Path("/tmp/huggingface/datasets")
    assert "Fetch the dataset yourself" in str(missing_cache_error(path))
    assert "does not use an API token" in str(empty_cache_error(path))


def test_tilde_hf_cache_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    missing = Path("~/.cache/huggingface/datasets/nope")
    with pytest.raises(AntiserumError, match="Fetch the dataset yourself"):
        ingest(missing)


def test_read_table_wraps_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Ipc:
        @staticmethod
        def open_file(_path: Path) -> object:
            raise ValueError("bad file")

        @staticmethod
        def open_stream(_path: Path) -> object:
            raise ValueError("bad stream")

    class _Parquet:
        @staticmethod
        def read_table(_path: Path) -> object:
            raise ValueError("bad parquet")

    class _Pa:
        ipc = _Ipc()
        parquet = _Parquet()

    monkeypatch.setattr(hf_local, "_require_pyarrow", lambda: _Pa)
    with pytest.raises(AntiserumError, match="not a readable local"):
        hf_local._read_table(tmp_path / "rows.parquet")
    with pytest.raises(AntiserumError, match="not a readable local"):
        hf_local._read_table(tmp_path / "rows.arrow")


def test_read_rows_table_to_pylist_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeTable:
        def to_pylist(self) -> list[dict]:
            raise RuntimeError("broken table")

    monkeypatch.setattr(hf_local, "_read_table", lambda _p: FakeTable())
    with pytest.raises(AntiserumError, match="could not read local"):
        read_rows(tmp_path / "rows.arrow")


def test_real_arrow_and_parquet_roundtrip(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table(
        {
            "id": ["arrow-1", "arrow-2"],
            "text": ["local arrow row", "second local arrow row"],
            "label": ["pos", "neg"],
        }
    )
    arrow_path = tmp_path / "rows.arrow"
    parquet_path = tmp_path / "rows.parquet"
    with arrow_path.open("wb") as fh:
        writer = pa.ipc.new_file(fh, table.schema)
        writer.write_table(table)
        writer.close()
    pa.parquet.write_table(table, parquet_path)

    arrow_records, _digest = ingest(arrow_path)
    assert [r.id for r in arrow_records] == ["arrow-1", "arrow-2"]
    assert arrow_records[0].text == "local arrow row"
    parquet_records, _digest = ingest(parquet_path)
    assert [r.id for r in parquet_records] == ["arrow-1", "arrow-2"]
    folder = tmp_path / "cache"
    folder.mkdir()
    (folder / "dataset_info.json").write_text("{}", encoding="utf-8")
    shard = folder / "dummy-train.arrow"
    shard.write_bytes(arrow_path.read_bytes())
    folder_records, _digest = ingest(folder)
    assert [r.id for r in folder_records] == ["arrow-1", "arrow-2"]
