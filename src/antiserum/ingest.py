from __future__ import annotations

import hashlib
import json
from pathlib import Path

from antiserum.errors import AntiserumError
from antiserum.models import Record

SUPPORTED_SUFFIXES = (".jsonl", ".txt")


def ingest(path: Path) -> tuple[list[Record], str]:
    """Load records from a file or folder. Returns (records, dataset_hash)."""
    root = path.resolve()
    if not root.exists():
        raise AntiserumError(f"path does not exist: {path}")

    files = _collect_files(root)
    if not files:
        kind = "file" if root.is_file() else "folder"
        raise AntiserumError(
            f"no .jsonl or .txt {kind} to scan at {path}. "
            "JSONL rows must be objects with a string 'text' field."
        )

    records: list[Record] = []
    for file_path in files:
        rel = _rel(file_path, root)
        if file_path.suffix.lower() == ".jsonl":
            records.extend(_read_jsonl(file_path, rel))
        else:
            records.extend(_read_txt(file_path, rel))

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


def _read_jsonl(path: Path, source: str) -> list[Record]:
    text = _read_bytes(path)
    records: list[Record] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AntiserumError(
                f"{source}:{lineno}: invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(obj, dict):
            raise AntiserumError(
                f"{source}:{lineno}: expected a JSON object, got {type(obj).__name__}"
            )
        if "text" not in obj:
            raise AntiserumError(
                f"{source}:{lineno}: missing required field 'text'"
            )
        if not isinstance(obj["text"], str):
            raise AntiserumError(
                f"{source}:{lineno}: field 'text' must be a string, "
                f"got {type(obj['text']).__name__}"
            )
        rec_id = _optional_id(obj.get("id"), source, lineno)
        label = _optional_label(obj.get("label"), source, lineno)
        records.append(
            Record(
                id=rec_id,
                text=obj["text"],
                label=label,
                source=source,
                line=lineno,
            )
        )
    return records


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
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()
