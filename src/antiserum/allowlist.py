from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from antiserum.errors import AntiserumError
from antiserum.models import AllowlistRef, Flag, Record, SignatureHit
from antiserum.textutil import text_hash

FILENAME = "allowlist.jsonl"
ENTRY_KEYS = ("record_id", "sha256", "signature_id")


@dataclass(frozen=True)
class Allowlist:
    path: str
    hash: str
    record_ids: frozenset[str]
    sha256s: frozenset[str]
    signature_ids: frozenset[str]

    def ref(self) -> AllowlistRef:
        return AllowlistRef(path=self.path, hash=self.hash)


def resolve_allowlist(
    explicit: Path | None, dataset: Path | None = None
) -> Path | None:
    """Find a local allowlist. Explicit path wins; else dataset dir, then repo root."""
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise AntiserumError(f"allowlist not found: {explicit}")
        return path

    seen: set[Path] = set()
    for candidate in _search_paths(dataset):
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def load_allowlist(path: Path) -> Allowlist:
    if not path.exists():
        raise AntiserumError(f"allowlist not found: {path}")
    if not path.is_file():
        raise AntiserumError(f"allowlist is not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{path}: not valid UTF-8 text") from exc

    record_ids: set[str] = set()
    sha256s: set[str] = set()
    signature_ids: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AntiserumError(
                f"{path}:{lineno}: invalid JSON ({exc.msg})"
            ) from exc
        rec, digest, sig = _entry(obj, path, lineno)
        if rec:
            record_ids.add(rec)
        if digest:
            sha256s.add(digest)
        if sig:
            signature_ids.add(sig)

    return Allowlist(
        path=str(path),
        hash=_file_hash(path),
        record_ids=frozenset(record_ids),
        sha256s=frozenset(sha256s),
        signature_ids=frozenset(signature_ids),
    )


def apply_allowlist(
    allowlist: Allowlist,
    flags: Sequence[Flag],
    hits: Sequence[SignatureHit],
    records: Sequence[Record],
) -> tuple[list[Flag], list[SignatureHit]]:
    hashes = {rec.id: text_hash(rec.text) for rec in records}
    kept_flags = [
        flag for flag in flags if not _flag_allowed(allowlist, flag, hashes)
    ]
    kept_hits = [
        hit for hit in hits if not _hit_allowed(allowlist, hit, hashes)
    ]
    return kept_flags, kept_hits


def _search_paths(dataset: Path | None) -> list[Path]:
    paths: list[Path] = []
    if dataset is not None:
        root = Path(dataset)
        here = root if root.is_dir() else root.parent
        paths.append(here / FILENAME)
        repo = _repo_root(here)
        if repo is not None:
            paths.append(repo / FILENAME)
    cwd_repo = _repo_root(Path.cwd())
    if cwd_repo is not None:
        paths.append(cwd_repo / FILENAME)
    return paths


def _repo_root(start: Path) -> Path | None:
    here = start.resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _entry(obj: object, path: Path, lineno: int) -> tuple[str | None, str | None, str | None]:
    where = f"{path}:{lineno}"
    if not isinstance(obj, dict):
        raise AntiserumError(f"{where}: allowlist entry must be a JSON object")
    record_id = _optional_key(obj, "record_id", where)
    digest = _optional_hash(obj.get("sha256"), where)
    signature_id = _optional_key(obj, "signature_id", where)
    if record_id is None and digest is None and signature_id is None:
        raise AntiserumError(
            f"{where}: need one of {', '.join(ENTRY_KEYS)}"
        )
    return record_id, digest, signature_id


def _optional_key(obj: dict, key: str, where: str) -> str | None:
    if key not in obj or obj[key] is None:
        return None
    value = obj[key]
    if not isinstance(value, str) or not value.strip():
        raise AntiserumError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _optional_hash(value: object, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AntiserumError(f"{where}: 'sha256' must be a non-empty string")
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return text


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _flag_allowed(
    allowlist: Allowlist, flag: Flag, hashes: dict[str, str]
) -> bool:
    if flag.record_id in allowlist.record_ids:
        return True
    digest = hashes.get(flag.record_id)
    if digest and digest in allowlist.sha256s:
        return True
    sig = flag.evidence.get("signature_id")
    return isinstance(sig, str) and sig in allowlist.signature_ids


def _hit_allowed(
    allowlist: Allowlist, hit: SignatureHit, hashes: dict[str, str]
) -> bool:
    if hit.record_id in allowlist.record_ids:
        return True
    digest = hashes.get(hit.record_id)
    if digest and digest in allowlist.sha256s:
        return True
    return hit.signature_id in allowlist.signature_ids
