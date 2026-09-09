from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from antiserum import __version__
from antiserum.allowlist import apply_allowlist, load_allowlist, resolve_allowlist
from antiserum.checks import run_checks, select_checks
from antiserum.errors import AntiserumError
from antiserum.ingest import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_RECORDS,
    ProgressCallback,
    ingest,
)
from antiserum.models import Receipt, Record
from antiserum.signatures import identify_pack

FAIL_ON_CHOICES = ("any", "high", "never")
DEFAULT_FAIL_ON = "never"
EXIT_TRUNCATED = 3


def scan(
    path: Path,
    *,
    feed_path: Path | None = None,
    allowlist_path: Path | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    only_checks: Sequence[str] | None = None,
    skip_checks: Sequence[str] | None = None,
    progress: ProgressCallback | None = None,
) -> Receipt:
    receipt, _records = _scan_with_records(
        path,
        feed_path=feed_path,
        allowlist_path=allowlist_path,
        max_records=max_records,
        max_bytes=max_bytes,
        only_checks=only_checks,
        skip_checks=skip_checks,
        progress=progress,
    )
    return receipt


def _scan_with_records(
    path: Path,
    *,
    feed_path: Path | None = None,
    allowlist_path: Path | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    only_checks: Sequence[str] | None = None,
    skip_checks: Sequence[str] | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Receipt, list[Record]]:
    loaded = ingest(
        path,
        max_records=max_records,
        max_bytes=max_bytes,
        progress=progress,
        truncate=True,
    )
    records, dataset_hash = loaded
    truncated = loaded.truncated
    selected = select_checks(only=only_checks, skip=skip_checks)
    flags, hits = run_checks(records, feed_path=feed_path, checks=selected)
    resolved = resolve_allowlist(allowlist_path, path)
    applied = None
    if resolved is not None:
        allowlist = load_allowlist(resolved)
        flags, hits = apply_allowlist(allowlist, flags, hits, records)
        applied = allowlist.ref()
    receipt = Receipt(
        scanner="antiserum",
        version=__version__,
        path=str(path),
        dataset_hash=dataset_hash,
        record_count=len(records),
        flags=flags,
        signature_hits=hits,
        pack=identify_pack(feed_path),
        allowlist=applied,
        checks=[check.name for check in selected],
        truncated=truncated,
    )
    return receipt, records


def scan_exit_code(
    receipt: Receipt,
    fail_on: str = DEFAULT_FAIL_ON,
    *,
    allow_truncated: bool = False,
) -> int:
    """Exit code for a completed scan. Usage and I/O errors stay 2.

    A ceiling that stops the scan before the path is exhausted is exit 3,
    distinct from ``--fail-on`` poison. ``allow_truncated`` keeps the
    ``--fail-on`` gate for a deliberate sample; the receipt still records
    the truncation.
    """
    if receipt.truncated is not None and not allow_truncated:
        return EXIT_TRUNCATED
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
