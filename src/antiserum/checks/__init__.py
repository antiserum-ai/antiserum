from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from antiserum.checks.base import Check, ScanContext
from antiserum.checks.duplicate_inject import DuplicateInjectCheck
from antiserum.checks.hidden_unicode import HiddenUnicodeCheck
from antiserum.checks.instruction_override import InstructionOverrideCheck
from antiserum.checks.label_flips import LabelFlipsCheck
from antiserum.checks.paraphrase_overweight import ParaphraseOverweightCheck
from antiserum.checks.signature_hit import SignatureHitCheck
from antiserum.checks.stat_outliers import StatOutliersCheck
from antiserum.checks.trigger_ngrams import TriggerNgramsCheck
from antiserum.errors import AntiserumError
from antiserum.models import Flag, Record, SignatureHit


def default_checks() -> list[Check]:
    return [
        TriggerNgramsCheck(),
        LabelFlipsCheck(),
        DuplicateInjectCheck(),
        ParaphraseOverweightCheck(),
        StatOutliersCheck(),
        SignatureHitCheck(),
        InstructionOverrideCheck(),
        HiddenUnicodeCheck(),
    ]


def check_names() -> list[str]:
    return [check.name for check in default_checks()]


def parse_check_names(raw: str, *, flag: str) -> list[str]:
    names = [part.strip() for part in raw.split(",")]
    names = [name for name in names if name]
    if not names:
        raise AntiserumError(f"{flag} requires at least one check name")
    return names


def select_checks(
    *,
    only: Sequence[str] | None = None,
    skip: Sequence[str] | None = None,
) -> list[Check]:
    if only is not None and skip is not None:
        raise AntiserumError(
            "--only-checks and --skip-checks cannot be used together"
        )
    available = default_checks()
    known = [check.name for check in available]
    known_set = set(known)
    requested: list[str] = []
    if only is not None:
        requested = list(only)
    elif skip is not None:
        requested = list(skip)
    unknown: list[str] = []
    seen: set[str] = set()
    for name in requested:
        if name in known_set or name in seen:
            continue
        seen.add(name)
        unknown.append(name)
    if unknown:
        raise AntiserumError(
            f"unknown check name(s): {', '.join(unknown)}. "
            f"known: {', '.join(known)}"
        )
    if only is not None:
        wanted = set(only)
        return [check for check in available if check.name in wanted]
    if skip is not None:
        skipped = set(skip)
        return [check for check in available if check.name not in skipped]
    return available


def run_checks(
    records: Sequence[Record],
    *,
    feed_path: Path | None = None,
    checks: Sequence[Check] | None = None,
) -> tuple[list[Flag], list[SignatureHit]]:
    ctx = ScanContext(feed_path=feed_path)
    flags: list[Flag] = []
    hits: list[SignatureHit] = []
    for check in checks if checks is not None else default_checks():
        result = check.run(records, ctx)
        flags.extend(result.flags)
        hits.extend(result.hits)
    flags.sort(key=lambda f: f.sort_key())
    hits.sort(key=lambda h: h.sort_key())
    return flags, hits
