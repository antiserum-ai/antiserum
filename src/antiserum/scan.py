from __future__ import annotations

from pathlib import Path

from antiserum import __version__
from antiserum.checks import run_checks
from antiserum.ingest import ingest
from antiserum.models import Receipt


def scan(path: Path, *, feed_path: Path | None = None) -> Receipt:
    records, dataset_hash = ingest(path)
    flags, hits = run_checks(records, feed_path=feed_path)
    return Receipt(
        scanner="antiserum",
        version=__version__,
        path=str(path),
        dataset_hash=dataset_hash,
        record_count=len(records),
        flags=flags,
        signature_hits=hits,
    )
