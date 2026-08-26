from __future__ import annotations

import os
from pathlib import Path


def resolve_feed(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    env = os.environ.get("ANTISERUM_FEED")
    if env:
        return Path(env)
    here = Path.cwd().resolve()
    for parent in (here, *here.parents):
        candidate = parent / "feed" / "signatures.jsonl"
        if candidate.is_file():
            return candidate
    return None
