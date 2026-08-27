from __future__ import annotations

import hashlib
import json
from pathlib import Path

from antiserum.errors import AntiserumError
from antiserum.models import PACK_COVERAGE, Pack

MATCH_TYPES = ("literal", "regex", "sha256")


def identify_pack(path: Path | None) -> Pack:
    """Hash the local feed file. Does not fetch a remote feed."""
    if path is None:
        return Pack.none()
    feed = Path(path)
    if not feed.is_file():
        return Pack.none()
    digest = hashlib.sha256(feed.read_bytes()).hexdigest()
    return Pack(
        path=str(path),
        hash="sha256:" + digest,
        signature_count=len(load_signatures(feed)),
        coverage=PACK_COVERAGE,
    )


def load_signatures(path: Path) -> list[dict]:
    if not path.exists():
        raise AntiserumError(f"signature feed not found: {path}")
    if not path.is_file():
        raise AntiserumError(f"signature feed is not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{path}: not valid UTF-8 text") from exc

    signatures: list[dict] = []
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
        sig = _validate(obj, path, lineno)
        signatures.append(sig)
    return signatures


def _validate(obj: object, path: Path, lineno: int) -> dict:
    where = f"{path}:{lineno}"
    if not isinstance(obj, dict):
        raise AntiserumError(f"{where}: signature must be a JSON object")
    missing = [k for k in ("id", "match", "pattern") if k not in obj]
    if missing:
        raise AntiserumError(
            f"{where}: missing required field(s): {', '.join(missing)}"
        )
    if not isinstance(obj["id"], str) or not obj["id"].strip():
        raise AntiserumError(f"{where}: 'id' must be a non-empty string")
    if obj["match"] not in MATCH_TYPES:
        raise AntiserumError(
            f"{where}: 'match' must be one of {', '.join(MATCH_TYPES)}"
        )
    if not isinstance(obj["pattern"], str) or not obj["pattern"]:
        raise AntiserumError(f"{where}: 'pattern' must be a non-empty string")
    if "confidence" in obj and obj["confidence"] is not None:
        if not isinstance(obj["confidence"], (int, float)) or isinstance(
            obj["confidence"], bool
        ):
            raise AntiserumError(f"{where}: 'confidence' must be a number")
        if not 0 <= float(obj["confidence"]) <= 1:
            raise AntiserumError(f"{where}: 'confidence' must be between 0 and 1")
    if "example_hashes" in obj and obj["example_hashes"] is not None:
        hashes = obj["example_hashes"]
        if not isinstance(hashes, list) or not all(isinstance(h, str) for h in hashes):
            raise AntiserumError(f"{where}: 'example_hashes' must be a list of strings")
    return obj
