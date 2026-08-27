from __future__ import annotations

from pathlib import Path

from antiserum import __version__
from antiserum.checks import run_checks
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.models import Receipt
from antiserum.signatures import identify_pack

FAIL_ON_CHOICES = ("any", "high", "never")
DEFAULT_FAIL_ON = "never"


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
        pack=identify_pack(feed_path),
    )


def scan_exit_code(receipt: Receipt, fail_on: str = DEFAULT_FAIL_ON) -> int:
    """Exit code for a completed scan. Usage and I/O errors stay 2."""
    if fail_on == "never":
        return 0
    if fail_on == "any":
        return 1 if receipt.flags else 0
    if fail_on == "high":
        return 1 if any(flag.severity == "high" for flag in receipt.flags) else 0
    raise AntiserumError(
        f"unknown --fail-on value: {fail_on}. "
        f"expected one of {', '.join(FAIL_ON_CHOICES)}"
    )
