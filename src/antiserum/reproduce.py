"""Scan the reference corpus and fail if planted rows are missed."""

from __future__ import annotations

from pathlib import Path

from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.reference import (
    DEFAULT_MAX_CLEAN_RATE,
    Score,
    format_score,
    load_manifest,
    resolve_reference,
    score_receipt,
)
from antiserum.scan import scan


def reproduce(
    path: Path | None = None,
    *,
    feed_path: Path | None = None,
    max_clean_rate: float = DEFAULT_MAX_CLEAN_RATE,
) -> tuple[Score, str]:
    """Scan `path` (default: corpus/reference) and score it against the manifest."""
    target = resolve_reference(path)
    manifest = load_manifest(target)
    records, _digest = ingest(target)
    plant_ids = manifest.plant_ids()
    missing_rows = sorted(plant_ids - {r.id for r in records})
    if missing_rows:
        preview = ", ".join(missing_rows[:8])
        extra = f" (+{len(missing_rows) - 8} more)" if len(missing_rows) > 8 else ""
        raise AntiserumError(
            f"manifest plants not in the mix: {preview}{extra}"
        )
    receipt = scan(target, feed_path=feed_path)
    score = score_receipt(
        receipt, manifest, records, max_clean_rate=max_clean_rate
    )
    return score, format_score(score, path=str(target))
