from __future__ import annotations

import hashlib
import json
from pathlib import Path

from antiserum.errors import AntiserumError
from antiserum.models import Record

SUPPORTED_SUFFIXES = (".jsonl", ".txt")
SKIP_NAMES = frozenset({"allowlist.jsonl"})
# Parts from Alpaca / messages / prompt+completion are joined with this.
SHAPE_JOIN = "\n\n"
_SHAPE_FIX = (
    "add a string 'text' field, or use instruction/input/output, "
    "messages/conversations, or prompt+completion"
)
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

    JSONL is streamed line-by-line. Source files are hashed in chunks.
    The mix is still held in memory after ingest: every v0 check needs
    the full row list. Mixes over ``max_records`` or ``max_bytes`` fail
    with a size error instead of an OOM. Dataset hash is sha256 over the
    ingested file bytes (same folder bytes → same hash).

    JSONL objects become one ``Record`` each. Checks run on ``Record.text``:

    - ``text`` — used as-is
    - Alpaca ``instruction`` / ``input`` / ``output`` — those strings, in
      that order, blank parts dropped, joined with a blank line
    - ShareGPT / chat ``messages`` or ``conversations`` — each turn's
      ``content`` or ``value``, same join
    - Hugging Face ``prompt`` + ``completion`` — those strings, same join
    """
    if max_records < 1:
        raise AntiserumError(f"max_records must be at least 1, got {max_records}")
    if max_bytes < 1:
        raise AntiserumError(f"max_bytes must be at least 1, got {max_bytes}")

    root = path.resolve()
    if not root.exists():
        raise AntiserumError(f"path does not exist: {path}")

    files = _collect_files(root)
    if not files:
        kind = "file" if root.is_file() else "folder"
        raise AntiserumError(
            f"no .jsonl or .txt {kind} to scan at {path}. "
            f"JSONL rows: {_SHAPE_FIX}."
        )

    source_bytes = sum(file_path.stat().st_size for file_path in files)
    if source_bytes > max_bytes:
        raise AntiserumError(_bytes_limit_error(source_bytes, max_bytes))

    records: list[Record] = []
    for file_path in files:
        rel = _rel(file_path, root)
        if file_path.suffix.lower() == ".jsonl":
            records.extend(_read_jsonl(file_path, rel, max_records, len(records)))
        else:
            added = _read_txt(file_path, rel)
            if len(records) + len(added) > max_records:
                raise AntiserumError(_records_limit_error(max_records))
            records.extend(added)

    if not records:
        raise AntiserumError(
            f"no text records found in {path}. "
            "JSONL files were empty or contained only blank lines."
        )

    return records, _dataset_hash(files, root)


def _collect_files(root: Path) -> list[Path]:
    if root.is_file():
        if root.name.startswith("."):
            raise AntiserumError(f"refusing hidden file: {root}")
        if root.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise AntiserumError(
                f"unsupported file type {root.suffix or '(no extension)'}: {root}. "
                "expected .jsonl or .txt"
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
        if child.name in SKIP_NAMES:
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
                rec_id = _optional_id(obj.get("id"), source, lineno)
                label = _optional_label(obj.get("label"), source, lineno)
                records.append(
                    Record(
                        id=rec_id,
                        text=_row_text(obj, source, lineno),
                        label=label,
                        source=source,
                        line=lineno,
                    )
                )
    except UnicodeDecodeError as exc:
        raise AntiserumError(
            f"{path}: not valid UTF-8 text ({exc.reason} at byte {exc.start})"
        ) from exc
    return records


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
