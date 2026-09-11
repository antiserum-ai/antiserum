from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from antiserum.errors import AntiserumError
from antiserum.hf_local import (
    ARROW_SUFFIXES,
    HF_META_NAMES,
    empty_cache_error,
    looks_like_hf_dir,
    looks_like_hf_path,
    missing_cache_error,
    read_rows,
)
from antiserum.models import Record, Truncation

ProgressCallback = Callable[[int, int, int], None]


class IngestResult:
    """Load result. Unpacks as ``(records, dataset_hash)`` for existing callers."""

    __slots__ = ("records", "dataset_hash", "truncated")

    def __init__(
        self,
        records: list[Record],
        dataset_hash: str,
        truncated: Truncation | None = None,
    ) -> None:
        self.records = records
        self.dataset_hash = dataset_hash
        self.truncated = truncated

    def __iter__(self) -> Iterator[object]:
        yield self.records
        yield self.dataset_hash

    def __getitem__(self, index: int) -> object:
        return (self.records, self.dataset_hash)[index]

GZIP_KINDS = {
    (".jsonl", ".gz"): "jsonl",
    (".json", ".gz"): "json",
    (".csv", ".gz"): "csv",
}
PLAIN_KINDS = {
    ".jsonl": "jsonl",
    ".json": "json",
    ".csv": "csv",
    ".txt": "txt",
}
SKIP_NAMES = frozenset(
    {
        "allowlist.jsonl",
        "manifest.json",
        "thresholds.json",
        "eval.json",
    }
) | HF_META_NAMES
# Parts from Alpaca / messages / prompt+completion are joined with this.
SHAPE_JOIN = "\n\n"
_SHAPE_FIX = (
    "add a string 'text' field, or use instruction/input/output, "
    "messages/conversations, or prompt+completion"
)
_SUFFIX_HINT = (
    ".jsonl, .json, .csv, .txt, .jsonl.gz, .json.gz, .csv.gz, .arrow, or .parquet"
)
_GZIP_HINT = ".jsonl.gz, .csv.gz, or .json.gz"
_CSV_META_HEADERS = frozenset({"id", "label"})
_CSV_SHAPE_HEADERS = frozenset(
    {"text", "instruction", "input", "output", "prompt", "completion"}
)
_CSV_KNOWN_HEADERS = _CSV_META_HEADERS | _CSV_SHAPE_HEADERS
# v0 checks hold the mix in process. Jaccard clustering is O(n²).
# 25k / 128 MiB is above the ~1k reference and below a 10M-row dump.
DEFAULT_MAX_RECORDS = 25_000
DEFAULT_MAX_BYTES = 128 * 1024 * 1024
_HASH_CHUNK = 1024 * 1024
_IN_MEMORY_CHECKS = (
    "label_flips and duplicate_inject cluster every row (O(n²) Jaccard); "
    "trigger_ngrams, pair_trigger, and stat_outliers also need the full mix "
    "in process"
)


def ingest(
    path: Path,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    progress: ProgressCallback | None = None,
    truncate: bool = False,
) -> IngestResult:
    """Load records from a file or folder. Returns (records, dataset_hash).

    JSONL is streamed line-by-line. CSV is streamed row-by-row. A ``.json``
    file must be one JSON array of objects (not JSONL). ``.jsonl.gz``,
    ``.csv.gz``, and ``.json.gz`` use stdlib ``gzip`` the same way (no
    ``gunzip`` shell-out). Source files are hashed in chunks. The mix is
    still held in memory after ingest: every v0 check needs the full row
    list. Mixes over ``max_records`` or ``max_bytes`` fail with a size
    error instead of an OOM unless ``truncate=True``, in which case ingest
    stops at the ceiling, leaves the unread tail on disk, and records
    which limit hit. Dataset hash is sha256 over the source file bytes
    as they sit on disk, including compressed dumps (same folder bytes →
    same hash). Decompressed text is not hashed. The unread tail is not
    uploaded.

    ``progress(records, bytes_done, bytes_total)`` is an optional local
    callback during ingest. It does not change the records or hash.

    JSONL / CSV / JSON-array objects become one ``Record`` each. Checks
    run on ``Record.text``:

    - ``text`` — used as-is
    - Alpaca ``instruction`` / ``input`` / ``output`` — those strings, in
      that order, blank parts dropped, joined with a blank line
    - ShareGPT / chat ``messages`` or ``conversations`` — each turn's
      ``content`` or ``value``, same join
    - Hugging Face ``prompt`` + ``completion`` — those strings, same join

    A local Hugging Face cache, Hub snapshot, or ``save_to_disk`` folder is
    a path like any other. Arrow and Parquet use the optional ``hf`` extra
    (pyarrow), imported only when those files are present. Missing cache
    dirs tell the user to fetch the dataset themselves. No Hub client.
    """
    if max_records < 1:
        raise AntiserumError(f"max_records must be at least 1, got {max_records}")
    if max_bytes < 1:
        raise AntiserumError(f"max_bytes must be at least 1, got {max_bytes}")

    root = path.expanduser().resolve()
    if not root.exists():
        if looks_like_hf_path(path):
            raise missing_cache_error(path)
        raise AntiserumError(f"path does not exist: {path}")

    files = _collect_files(root)
    if not files:
        if looks_like_hf_dir(root) or looks_like_hf_path(path):
            raise empty_cache_error(path)
        kind = "file" if root.is_file() else "folder"
        raise AntiserumError(
            f"no {_SUFFIX_HINT} {kind} to scan at {path}. "
            f"JSONL rows: {_SHAPE_FIX}."
        )

    source_bytes = sum(file_path.stat().st_size for file_path in files)
    if source_bytes > max_bytes and not truncate:
        raise AntiserumError(_bytes_limit_error(source_bytes, max_bytes))

    records: list[Record] = []
    bytes_done = 0
    ceiling: str | None = None

    def _progress(n_records: int) -> None:
        if progress is not None:
            progress(n_records, bytes_done, source_bytes)

    _progress(0)
    for file_path in files:
        if ceiling is not None:
            break
        if truncate and len(records) >= max_records:
            ceiling = "records"
            break
        rel = _rel(file_path, root)
        kind = _kind(file_path)
        file_size = file_path.stat().st_size
        if (
            truncate
            and kind not in ("jsonl", "csv")
            and bytes_done + file_size > max_bytes
        ):
            ceiling = "bytes"
            break
        if kind == "jsonl":
            added, hit, prefix = _read_jsonl(
                file_path,
                rel,
                max_records,
                len(records),
                _progress,
                truncate=truncate,
                max_bytes=max_bytes,
                bytes_already=bytes_done,
            )
            records.extend(added)
            if hit is not None:
                ceiling = hit
                bytes_done += prefix
            else:
                bytes_done += file_size
        elif kind == "json":
            added, hit = _read_json_array(
                file_path,
                rel,
                max_records,
                len(records),
                _progress,
                truncate=truncate,
            )
            records.extend(added)
            bytes_done += file_size
            if hit is not None:
                ceiling = hit
        elif kind == "csv":
            added, hit, prefix = _read_csv(
                file_path,
                rel,
                max_records,
                len(records),
                _progress,
                truncate=truncate,
                max_bytes=max_bytes,
                bytes_already=bytes_done,
            )
            records.extend(added)
            if hit is not None:
                ceiling = hit
                bytes_done += prefix
            else:
                bytes_done += file_size
        elif kind == "arrow":
            added, hit = _read_arrow(
                file_path,
                rel,
                already=len(records),
                on_progress=_progress,
                max_records=max_records,
                truncate=truncate,
            )
            records.extend(added)
            bytes_done += file_size
            if hit is not None:
                ceiling = hit
        else:
            added = _read_txt(file_path, rel)
            if len(records) + len(added) > max_records:
                if truncate:
                    ceiling = "records"
                    break
                raise AntiserumError(_records_limit_error(max_records))
            records.extend(added)
            bytes_done += file_size
            _progress(len(records))
        _progress(len(records))

    if not records and ceiling is None:
        raise AntiserumError(
            f"no text records found in {path}. "
            "files were empty or contained only blank lines."
        )

    truncated = (
        Truncation(
            ceiling=ceiling,
            records_seen=len(records),
            bytes_seen=bytes_done,
        )
        if ceiling is not None
        else None
    )
    return IngestResult(records, _dataset_hash(files, root), truncated)


def _suffixes(path: Path) -> tuple[str, ...]:
    return tuple(part.lower() for part in path.suffixes)


def _kind(path: Path) -> str | None:
    suffixes = _suffixes(path)
    if not suffixes:
        return None
    if suffixes[-1] == ".gz":
        return GZIP_KINDS.get(suffixes[-2:])
    if suffixes[-1] in ARROW_SUFFIXES:
        return "arrow"
    return PLAIN_KINDS.get(suffixes[-1])


def _is_gzip_dump(path: Path) -> bool:
    suffixes = _suffixes(path)
    return len(suffixes) >= 2 and suffixes[-2:] in GZIP_KINDS


def _is_unknown_gzip(path: Path) -> bool:
    suffixes = _suffixes(path)
    return bool(suffixes) and suffixes[-1] == ".gz" and not _is_gzip_dump(path)


def _gzip_error(path: Path, exc: BaseException) -> AntiserumError:
    return AntiserumError(f"{path}: invalid gzip ({exc})")


@contextmanager
def _open_text(path: Path, *, newline: str | None = None) -> Iterator[TextIO]:
    try:
        if _is_gzip_dump(path):
            handle = gzip.open(path, "rt", encoding="utf-8", newline=newline)
        elif newline is not None:
            handle = path.open(encoding="utf-8", newline=newline)
        else:
            handle = path.open(encoding="utf-8")
    except (OSError, EOFError) as exc:
        if _is_gzip_dump(path):
            raise _gzip_error(path, exc) from exc
        raise
    try:
        yield handle
    except UnicodeDecodeError as exc:
        raise AntiserumError(
            f"{path}: not valid UTF-8 text ({exc.reason} at byte {exc.start})"
        ) from exc
    except (OSError, EOFError) as exc:
        if _is_gzip_dump(path):
            raise _gzip_error(path, exc) from exc
        raise
    finally:
        handle.close()


def _collect_files(root: Path) -> list[Path]:
    if root.is_file():
        if root.name.startswith("."):
            raise AntiserumError(f"refusing hidden file: {root}")
        if _is_unknown_gzip(root):
            raise AntiserumError(
                f"unknown gzip suffix {root.name}: {root}. expected {_GZIP_HINT}"
            )
        if _kind(root) is None:
            raise AntiserumError(
                f"unsupported file type {root.suffix or '(no extension)'}: {root}. "
                f"expected {_SUFFIX_HINT}"
            )
        return [root]

    if not root.is_dir():
        raise AntiserumError(f"not a file or folder: {root}")

    found: list[Path] = []
    unknown_gz: list[Path] = []
    for child in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if not child.is_file():
            continue
        if child.name.startswith("."):
            continue
        if child.name.lower() in SKIP_NAMES:
            continue
        if _is_unknown_gzip(child):
            unknown_gz.append(child)
            continue
        if _kind(child) is not None:
            found.append(child)
    if not found and unknown_gz:
        first = unknown_gz[0]
        raise AntiserumError(
            f"unknown gzip suffix {first.name}: {first}. expected {_GZIP_HINT}"
        )
    return found


def _rel(file_path: Path, root: Path) -> str:
    if file_path == root:
        return file_path.name
    try:
        return file_path.relative_to(root).as_posix()
    except ValueError:
        return file_path.name


def _read_bytes(path: Path) -> str:
    with _open_text(path) as handle:
        return handle.read()


def _read_jsonl(
    path: Path,
    source: str,
    max_records: int,
    already: int,
    on_progress: Callable[[int], None] | None = None,
    *,
    truncate: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    bytes_already: int = 0,
) -> tuple[list[Record], str | None, int]:
    records: list[Record] = []
    accepted_bytes = 0
    with _open_text(path) as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            row_bytes = len(raw.encode("utf-8"))
            if already + len(records) + 1 > max_records:
                if truncate:
                    return records, "records", accepted_bytes
                raise AntiserumError(_records_limit_error(max_records))
            if truncate and bytes_already + accepted_bytes + row_bytes > max_bytes:
                return records, "bytes", accepted_bytes
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AntiserumError(
                    f"{source}:{lineno}: invalid JSON ({exc.msg})"
                ) from exc
            if not isinstance(obj, dict):
                raise AntiserumError(
                    f"{source}:{lineno}: expected a JSON object, got "
                    f"{type(obj).__name__}"
                )
            records.append(_record_from_obj(obj, source, lineno))
            accepted_bytes += row_bytes
            if on_progress is not None:
                on_progress(already + len(records))
    return records, None, accepted_bytes


def _read_json_array(
    path: Path,
    source: str,
    max_records: int,
    already: int,
    on_progress: Callable[[int], None] | None = None,
    *,
    truncate: bool = False,
) -> tuple[list[Record], str | None]:
    try:
        payload = json.loads(_read_bytes(path))
    except json.JSONDecodeError as exc:
        raise AntiserumError(
            f"{source}: invalid JSON ({exc.msg}). "
            "a .json file must be one JSON array of objects; "
            "for one object per line use .jsonl"
        ) from exc
    if not isinstance(payload, list):
        raise AntiserumError(
            f"{source}: expected a JSON array of objects, got "
            f"{type(payload).__name__}. wrap rows in [ ], or use .jsonl "
            f"for one object per line"
        )
    records: list[Record] = []
    for index, obj in enumerate(payload, start=1):
        if already + len(records) + 1 > max_records:
            if truncate:
                return records, "records"
            raise AntiserumError(_records_limit_error(max_records))
        if not isinstance(obj, dict):
            raise AntiserumError(
                f"{source}:{index}: expected a JSON object, got "
                f"{type(obj).__name__}"
            )
        records.append(_record_from_obj(obj, source, index))
        if on_progress is not None:
            on_progress(already + len(records))
    return records, None


class _CountingLines:
    """Count UTF-8 bytes as lines are read. Avoids ``tell()`` after csv next()."""

    def __init__(self, handle: TextIO) -> None:
        self._handle = handle
        self.bytes_read = 0

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        raw = next(self._handle)
        self.bytes_read += len(raw.encode("utf-8"))
        return raw


def _read_csv(
    path: Path,
    source: str,
    max_records: int,
    already: int,
    on_progress: Callable[[int], None] | None = None,
    *,
    truncate: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    bytes_already: int = 0,
) -> tuple[list[Record], str | None, int]:
    records: list[Record] = []
    accepted_bytes = 0
    with _open_text(path, newline="") as handle:
        counted = _CountingLines(handle)
        reader = csv.DictReader(counted)
        _check_csv_headers(reader.fieldnames, source)
        for lineno, row in enumerate(reader, start=2):
            if None in row:
                raise AntiserumError(
                    f"{source}:{lineno}: CSV row has more fields than "
                    f"headers. {_SHAPE_FIX}."
                )
            if all(value is None or str(value).strip() == "" for value in row.values()):
                continue
            if already + len(records) + 1 > max_records:
                if truncate:
                    return records, "records", accepted_bytes
                raise AntiserumError(_records_limit_error(max_records))
            if truncate and bytes_already + counted.bytes_read > max_bytes:
                return records, "bytes", accepted_bytes
            obj = {
                key: ("" if value is None else value) for key, value in row.items()
            }
            records.append(_record_from_obj(obj, source, lineno))
            accepted_bytes = counted.bytes_read
            if on_progress is not None:
                on_progress(already + len(records))
    return records, None, accepted_bytes


def _check_csv_headers(fieldnames: list[str] | None, source: str) -> None:
    if not fieldnames:
        raise AntiserumError(f"{source}: CSV has no header row. {_SHAPE_FIX}.")
    headers = list(fieldnames)
    if any(header is None or header == "" for header in headers):
        raise AntiserumError(f"{source}: CSV has an empty header. {_SHAPE_FIX}.")
    if len(headers) != len(set(headers)):
        raise AntiserumError(f"{source}: CSV has duplicate headers. {_SHAPE_FIX}.")
    unknown = [header for header in headers if header not in _CSV_KNOWN_HEADERS]
    if unknown:
        raise AntiserumError(
            f"{source}: unknown CSV header(s): {', '.join(unknown)}. {_SHAPE_FIX}."
        )
    if not any(header in _CSV_SHAPE_HEADERS for header in headers):
        keys = ", ".join(headers)
        raise AntiserumError(
            f"{source}: unknown row shape (keys: {keys}). {_SHAPE_FIX}."
        )


def _record_from_obj(obj: dict, source: str, lineno: int) -> Record:
    return Record(
        id=_optional_id(obj.get("id"), source, lineno),
        text=_row_text(obj, source, lineno),
        label=_optional_label(obj.get("label"), source, lineno),
        source=source,
        line=lineno,
    )


def _row_text(obj: dict, source: str, lineno: int) -> str:
    if "text" in obj:
        return _require_str(obj, "text", source, lineno)
    if "instruction" in obj:
        return _join_fields(obj, ("instruction", "input", "output"), source, lineno)
    if "messages" in obj or "conversations" in obj:
        return _messages_text(obj, source, lineno)
    if "prompt" in obj or "completion" in obj:
        return _join_fields(
            obj, ("prompt", "completion"), source, lineno, required=True
        )
    keys = ", ".join(sorted(obj)) or "none"
    raise AntiserumError(
        f"{source}:{lineno}: unknown row shape (keys: {keys}). {_SHAPE_FIX}."
    )


def _require_str(obj: dict, key: str, source: str, lineno: int) -> str:
    value = obj[key]
    if not isinstance(value, str):
        raise AntiserumError(
            f"{source}:{lineno}: field '{key}' must be a string, "
            f"got {type(value).__name__}"
        )
    return value


def _join_fields(
    obj: dict,
    keys: tuple[str, ...],
    source: str,
    lineno: int,
    *,
    required: bool = False,
) -> str:
    parts: list[str] = []
    for key in keys:
        if key not in obj:
            if required:
                raise AntiserumError(
                    f"{source}:{lineno}: missing '{key}'. {_SHAPE_FIX}."
                )
            continue
        value = _require_str(obj, key, source, lineno)
        if value.strip():
            parts.append(value)
    if not parts:
        raise AntiserumError(
            f"{source}:{lineno}: empty {'/'.join(keys)} row. {_SHAPE_FIX}."
        )
    return SHAPE_JOIN.join(parts)


def _messages_text(obj: dict, source: str, lineno: int) -> str:
    key = "messages" if "messages" in obj else "conversations"
    items = obj[key]
    if not isinstance(items, list) or not items:
        raise AntiserumError(
            f"{source}:{lineno}: field '{key}' must be a non-empty list. "
            f"{_SHAPE_FIX}."
        )
    parts: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise AntiserumError(
                f"{source}:{lineno}: {key}[{index}] must be an object, "
                f"got {type(item).__name__}. {_SHAPE_FIX}."
            )
        if isinstance(item.get("content"), str):
            value = item["content"]
        elif isinstance(item.get("value"), str):
            value = item["value"]
        else:
            raise AntiserumError(
                f"{source}:{lineno}: {key}[{index}] needs a string "
                f"'content' or 'value'. {_SHAPE_FIX}."
            )
        if value.strip():
            parts.append(value)
    if not parts:
        raise AntiserumError(
            f"{source}:{lineno}: empty {key} row. {_SHAPE_FIX}."
        )
    return SHAPE_JOIN.join(parts)


def _read_arrow(
    path: Path,
    source: str,
    *,
    already: int = 0,
    on_progress: Callable[[int], None] | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    truncate: bool = False,
) -> tuple[list[Record], str | None]:
    records: list[Record] = []
    for lineno, obj in enumerate(read_rows(path), start=1):
        if already + len(records) + 1 > max_records:
            if truncate:
                return records, "records"
            raise AntiserumError(_records_limit_error(max_records))
        records.append(_record_from_obj(obj, source, lineno))
        if on_progress is not None:
            on_progress(already + len(records))
    return records, None


def _read_txt(path: Path, source: str) -> list[Record]:
    text = _read_bytes(path)
    if text.strip() == "":
        return []
    return [
        Record(
            id=Path(source).stem,
            text=text,
            label=None,
            source=source,
            line=None,
        )
    ]


def _optional_id(value: object, source: str, lineno: int) -> str:
    if value is None:
        return f"{source}:{lineno}"
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        rec_id = str(value).strip()
        if rec_id:
            return rec_id
        return f"{source}:{lineno}"
    raise AntiserumError(
        f"{source}:{lineno}: field 'id' must be a string or number, "
        f"got {type(value).__name__}"
    )


def _optional_label(value: object, source: str, lineno: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        label = str(value).strip()
        return label or None
    raise AntiserumError(
        f"{source}:{lineno}: field 'label' must be a string or number, "
        f"got {type(value).__name__}"
    )


def _dataset_hash(files: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: _rel(p, root)):
        digest.update(_rel(path, root).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def _sha256_file(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()


def _records_limit_error(limit: int) -> str:
    return (
        f"corpus too large: more than {limit} records (limit {limit}). "
        f"{_IN_MEMORY_CHECKS}. "
        "raise max_records if this machine can hold it; "
        "there is no cluster or chunked check path"
    )


def _bytes_limit_error(size: int, limit: int) -> str:
    return (
        f"corpus too large: {size} bytes on disk (limit {limit}). "
        "v0 loads the mix in process. "
        f"{_IN_MEMORY_CHECKS}. "
        "raise max_bytes if this machine can hold it; "
        "there is no cluster or chunked check path"
    )
