"""Read a local Hugging Face dataset folder. Never a Hub client.

Point this at a cache dir you already fetched (`~/.cache/huggingface/datasets`,
a Hub snapshot, or a `save_to_disk` folder). Arrow and Parquet need the
optional ``hf`` extra (pyarrow). That extra is unused unless a local path
contains those files. No download, no API token, no ``huggingface_hub``.
"""

from __future__ import annotations

from pathlib import Path

from antiserum.errors import AntiserumError

ARROW_SUFFIXES = (".arrow", ".parquet")
HF_META_NAMES = frozenset(
    {
        "dataset_info.json",
        "dataset_dict.json",
        "state.json",
        "cache-version.txt",
        "hashes.json",
        "features.json",
    }
)
FETCH_YOURSELF = (
    "Fetch the dataset yourself and point antiserum at that local folder. "
    "This tool does not download from the Hub and does not use an API token."
)


def default_datasets_cache() -> Path:
    import os

    explicit = os.environ.get("HF_DATASETS_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "datasets"
    return Path.home() / ".cache" / "huggingface" / "datasets"


def looks_like_hf_path(path: Path) -> bool:
    """True when the path itself looks like a Hub/datasets cache location."""
    expanded = path.expanduser()
    parts = [part.lower() for part in expanded.parts]
    if "huggingface" in parts:
        return True
    if expanded.suffix.lower() in ARROW_SUFFIXES:
        return True
    return False


def looks_like_hf_dir(root: Path) -> bool:
    """True when a path on disk looks like a local HF cache or save_to_disk dir."""
    if looks_like_hf_path(root):
        return True
    if root.is_file():
        return root.name.lower() in HF_META_NAMES
    if not root.is_dir():
        return False
    try:
        children = list(root.iterdir())
    except OSError:
        return False
    names = {child.name.lower() for child in children}
    if names & HF_META_NAMES:
        return True
    for child in children:
        if child.is_file() and child.suffix.lower() in ARROW_SUFFIXES:
            return True
        if child.is_dir() and (child / "dataset_info.json").is_file():
            return True
    return False


def missing_cache_error(path: Path) -> AntiserumError:
    return AntiserumError(
        f"Hugging Face cache not found at {path}. {FETCH_YOURSELF}"
    )


def empty_cache_error(path: Path) -> AntiserumError:
    return AntiserumError(
        f"Hugging Face cache at {path} has no local dataset files to scan. "
        f"{FETCH_YOURSELF}"
    )


def read_rows(path: Path) -> list[dict]:
    """Load one local Arrow or Parquet file as a list of JSON-like objects."""
    table = _read_table(path)
    try:
        rows = table.to_pylist()
    except Exception as exc:
        raise AntiserumError(
            f"{path}: could not read local Arrow/Parquet rows ({exc})"
        ) from exc
    out: list[dict] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise AntiserumError(
                f"{path}: row {index} is {type(row).__name__}, expected an object"
            )
        out.append(row)
    return out


def _read_table(path: Path):
    pa = _require_pyarrow()
    suffix = path.suffix.lower()
    try:
        if suffix == ".parquet":
            return pa.parquet.read_table(path)
        try:
            return pa.ipc.open_file(path).read_all()
        except Exception:
            return pa.ipc.open_stream(path).read_all()
    except AntiserumError:
        raise
    except Exception as exc:
        raise AntiserumError(
            f"{path}: not a readable local Arrow or Parquet file ({exc})"
        ) from exc


def _require_pyarrow():
    try:
        return _load_pyarrow()
    except ImportError as exc:
        raise AntiserumError(
            "found a local Hugging Face Arrow/Parquet file but pyarrow is "
            "not installed. Install the optional extra "
            "(pip install 'antiserum[hf]') and scan the local path again. "
            "This tool does not download."
        ) from exc


def _load_pyarrow():
    import pyarrow  # type: ignore[import-untyped]
    import pyarrow.ipc  # type: ignore[import-untyped]
    import pyarrow.parquet  # type: ignore[import-untyped]

    return pyarrow
