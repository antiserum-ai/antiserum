from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

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
from antiserum.models import Record

SUPPORTED_SUFFIXES = (".jsonl", ".json", ".csv", ".txt") + ARROW_SUFFIXES
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
_SUFFIX_HINT = ".jsonl, .json, .csv, .txt, .arrow, or .parquet"
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
    "trigger_ngrams and stat_outliers also need the full mix in process"
)


def ingest(
    path: Path,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[list[Record], str]:
    """Load records from a file or folder. Returns (records, dataset_hash).

    JSONL is streamed line-by-line. CSV is streamed row-by-row. A ``.json``
    file must be one JSON array of objects (not JSONL). Source files are
    hashed in chunks. The mix is still held in memory after ingest: every
    v0 check needs the full row list. Mixes over ``max_records`` or
    ``max_bytes`` fail with a size error instead of an OOM. Dataset hash
    is sha256 over the ingested file bytes (same folder bytes → same hash).

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
    if source_bytes > max_bytes:
        raise AntiserumError(_bytes_limit_error(source_bytes, max_bytes))

    records: list[Record] = []
    for file_path in files:
        rel = _rel(file_path, root)
        suffix = file_path.suffix.lower()
        if suffix == ".jsonl":
            records.extend(_read_jsonl(file_path, rel, max_records, len(records)))
        elif suffix == ".json":
            records.extend(_read_json_array(file_path, rel, max_records, len(records)))
        elif suffix == ".csv":
            records.extend(_read_csv(file_path, rel, max_records, len(records)))
        elif suffix in ARROW_SUFFIXES:
            added = _read_arrow(file_path, rel)
            if len(records) + len(added) > max_records:
                raise AntiserumError(_records_limit_error(max_records))
            records.extend(added)
        else:
            added = _read_txt(file_path, rel)
            if len(records) + len(added) > max_records:
                raise AntiserumError(_records_limit_error(max_records))
            records.extend(added)

    if not records:
        raise AntiserumError(
            f"no text records found in {path}. "
            "files were empty or contained only blank lines."
        )

    return records, _dataset_hash(files, root)


def _collect_files(root: Path) -> list[Path]:
    if root.is_file():
        if root.name.startswith("."):
            raise AntiserumError(f"refusing hidden file: {root}")
        if root.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise AntiserumError(
                f"unsupported file type {root.suffix or '(no extension)'}: {root}. "
                f"expected {_SUFFIX_HINT}"
            )
        return [root]

    if not root.is_dir():
        raise AntiserumError(f"not a file or folder: {root}")

    found: list[Path] = []
    for child in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if not child.is_file():
            continue
        if child.name.startswith("."):
            continue
        if child.name.lower() in SKIP_NAMES:
            continue
        if child.suffix.lower() in SUPPORTED_SUFFIXES:
            found.append(child)
    return found


def _rel(file_path: Path, root: Path) -> str:
    if file_path == root:
        return file_path.name
    try:
        return file_path.relative_to(root).as_posix()
    except ValueError:
        return file_path.name


def _read_bytes(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AntiserumError(
            f"{path}: not valid UTF-8 text ({exc.reason} at byte {exc.start})"
        ) from exc


def _read_jsonl(
    path: Path, source: str, max_records: int, already: int
) -> list[Record]:
    records: list[Record] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for lineno, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                if already + len(records) + 1 > max_records:
                    raise AntiserumError(_records_limit_error(max_records))
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
    except UnicodeDecodeError as exc:
        raise AntiserumError(
            f"{path}: not valid UTF-8 text ({exc.reason} at byte {exc.start})"
        ) from exc
    return records


def _read_json_array(
    path: Path, source: str, max_records: int, already: int
) -> list[Record]:
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
            raise AntiserumError(_records_limit_error(max_records))
        if not isinstance(obj, dict):
            raise AntiserumError(
                f"{source}:{index}: expected a JSON object, got "
                f"{type(obj).__name__}"
            )
        records.append(_record_from_obj(obj, source, index))
    return records


def _read_csv(
    path: Path, source: str, max_records: int, already: int
) -> list[Record]:
    records: list[Record] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
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
                    raise AntiserumError(_records_limit_error(max_records))
                obj = {
                    key: ("" if value is None else value) for key, value in row.items()
                }
                records.append(_record_from_obj(obj, source, lineno))
    except UnicodeDecodeError as exc:
        raise AntiserumError(
            f"{path}: not valid UTF-8 text ({exc.reason} at byte {exc.start})"
        ) from exc
    return records


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


def _read_arrow(path: Path, source: str) -> list[Record]:
    return [
        _record_from_obj(obj, source, lineno)
        for lineno, obj in enumerate(read_rows(path), start=1)
    ]


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
