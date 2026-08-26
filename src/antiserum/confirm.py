from __future__ import annotations

from collections.abc import Sequence

from antiserum.errors import AntiserumError
from antiserum.judge import utc_now
from antiserum.judgments import FINAL_DECISIONS, Judgment, JudgmentStore
from antiserum.models import Flag, Record
from antiserum.patterns import propose_signature


def settle(
    store: JudgmentStore,
    *,
    flag_key: str,
    decision: str,
    rationale: str,
    records: Sequence[Record] | None = None,
    flags: Sequence[Flag] | None = None,
    pattern: str | None = None,
    match: str = "literal",
    attack: str | None = None,
    now: str | None = None,
) -> Judgment:
    if decision not in FINAL_DECISIONS:
        raise AntiserumError(
            f"decision must be one of {', '.join(FINAL_DECISIONS)}"
        )
    if not rationale.strip():
        raise AntiserumError("rationale must be a non-empty string")

    current = store.by_flag_id().get(flag_key)
    if current is None:
        known = ", ".join(j.flag_id for j in store.sorted_judgments()) or "(none)"
        raise AntiserumError(f"unknown flag id {flag_key!r}. known: {known}")

    proposed = None
    if decision == "poison":
        if pattern:
            proposed = {
                "match": match,
                "pattern": pattern,
                "attack": attack or _attack_from_check(current.check),
                "confidence": 0.8,
                "notes": rationale.strip(),
            }
        else:
            record = _record_for(current.record_id, records)
            flag = _flag_for(current, flags)
            if record is not None and flag is not None:
                proposed = propose_signature(
                    flag,
                    record,
                    records or (),
                    notes=rationale.strip(),
                    confidence=0.8,
                )

    updated = Judgment(
        flag_id=current.flag_id,
        record_id=current.record_id,
        check=current.check,
        decision=decision,
        rationale=rationale.strip(),
        judge="human",
        timestamp=now or utc_now(),
        proposed_signature=proposed,
    )
    store.replace(updated)
    return updated


def _record_for(record_id: str, records: Sequence[Record] | None) -> Record | None:
    if not records:
        return None
    for rec in records:
        if rec.id == record_id:
            return rec
    return None


def _flag_for(judgment: Judgment, flags: Sequence[Flag] | None) -> Flag | None:
    if flags:
        for flag in flags:
            if flag.check == judgment.check and flag.record_id == judgment.record_id:
                return flag
    return Flag(
        check=judgment.check,
        record_id=judgment.record_id,
        severity="high",
        reason=judgment.rationale,
        evidence={},
    )


def _attack_from_check(check: str) -> str:
    return {
        "trigger_ngrams": "trigger",
        "label_flips": "label_flip",
        "duplicate_inject": "duplicate_inject",
        "stat_outliers": "stat_outlier",
        "signature_hit": "canary",
    }.get(check, check)
