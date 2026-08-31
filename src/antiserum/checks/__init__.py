from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from antiserum.checks.base import Check, ScanContext
from antiserum.checks.duplicate_inject import DuplicateInjectCheck
from antiserum.checks.label_flips import LabelFlipsCheck
from antiserum.checks.paraphrase_overweight import ParaphraseOverweightCheck
from antiserum.checks.signature_hit import SignatureHitCheck
from antiserum.checks.stat_outliers import StatOutliersCheck
from antiserum.checks.trigger_ngrams import TriggerNgramsCheck
from antiserum.models import Flag, Record, SignatureHit


def default_checks() -> list[Check]:
    return [
        TriggerNgramsCheck(),
        LabelFlipsCheck(),
        DuplicateInjectCheck(),
        ParaphraseOverweightCheck(),
        StatOutliersCheck(),
        SignatureHitCheck(),
    ]


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
