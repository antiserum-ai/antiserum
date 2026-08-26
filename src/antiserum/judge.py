from __future__ import annotations

import importlib
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from antiserum.judgments import Judgment, JudgmentStore, flag_id
from antiserum.models import Flag, Receipt, Record
from antiserum.patterns import looks_like_blob, propose_signature

JudgeFn = Callable[..., Judgment | None]


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def first_pass(
    receipt: Receipt,
    records: Sequence[Record],
    *,
    now: str | None = None,
    hook: JudgeFn | None = None,
) -> JudgmentStore:
    """Apply the published rubric. Offline and deterministic unless a hook is set."""
    timestamp = now or utc_now()
    by_id = {rec.id: rec for rec in records}
    siblings: dict[str, list[Flag]] = defaultdict(list)
    for flag in receipt.flags:
        siblings[flag.record_id].append(flag)

    hook_fn = hook if hook is not None else _load_hook()
    judgments: list[Judgment] = []
    for flag in sorted(receipt.flags, key=lambda f: f.sort_key()):
        record = by_id.get(flag.record_id)
        judged = None
        if hook_fn is not None:
            try:
                judged = hook_fn(
                    flag,
                    record,
                    flags=siblings[flag.record_id],
                    records=records,
                    now=timestamp,
                )
            except Exception:
                judged = None
        if judged is None:
            judged = _heuristic(
                flag,
                record,
                siblings=siblings[flag.record_id],
                records=records,
                now=timestamp,
            )
        judgments.append(judged)

    return JudgmentStore(
        path=receipt.path,
        dataset_hash=receipt.dataset_hash,
        receipt=None,
        scanner_version=receipt.version,
        judgments=judgments,
    )


def _heuristic(
    flag: Flag,
    record: Record | None,
    *,
    siblings: Sequence[Flag],
    records: Sequence[Record],
    now: str,
) -> Judgment:
    sibling_checks = {item.check for item in siblings}
    has_signature = "signature_hit" in sibling_checks
    has_dump = "duplicate_inject" in sibling_checks
    text = record.text if record is not None else ""

    if flag.check == "signature_hit":
        sig = flag.evidence.get("signature_id") or "feed"
        return _judgment(
            flag,
            "poison",
            (
                f"Signature {sig} already confirmed this row. "
                "A feed hit is published poison, not a new finding."
            ),
            now,
            proposed=None,
        )

    if flag.check == "duplicate_inject":
        copies = flag.evidence.get("copies")
        copy_n = int(copies) if isinstance(copies, int) else 0
        proposed = propose_signature(
            flag,
            record,
            records,
            notes=(
                f"Near-copy dump ({copy_n or 'several'} rows). "
                "Pattern is specific to the overweight cluster."
            ),
            confidence=0.9 if copy_n >= 6 else 0.8,
        )
        if proposed is not None:
            return _judgment(
                flag,
                "poison",
                (
                    f"High-confidence duplicate dump ({copy_n} copies). "
                    "The pattern is specific enough to add to the feed."
                ),
                now,
                proposed=proposed,
            )
        return _judgment(
            flag,
            "junk" if copy_n >= 4 and record is not None and looks_like_blob(text) else "needs_human",
            (
                "Duplicate cluster without a pattern that stays off clean rows. "
                "A human should decide if this is an overweight plant or sloppy collection."
            ),
            now,
        )

    if flag.check == "stat_outliers":
        if has_signature:
            return _judgment(
                flag,
                "poison",
                "Stat spike on a row that already matches a published signature.",
                now,
            )
        if record is not None and looks_like_blob(text):
            return _judgment(
                flag,
                "junk",
                (
                    "Length/entropy/alphabet spike looks like sloppy or synthetic blob "
                    "data, not a reusable planted attack. Do not add a signature."
                ),
                now,
            )
        return _judgment(
            flag,
            "false_alarm",
            (
                "Weak stat outlier on ordinary-looking text. "
                "Treat as a noisy check, not poison."
            ),
            now,
        )

    if flag.check == "trigger_ngrams":
        ngram = flag.evidence.get("ngram")
        ngram_s = ngram.strip() if isinstance(ngram, str) else ""
        distinctive = bool(ngram_s) and any(ch.isdigit() for ch in ngram_s)
        df = flag.evidence.get("df")
        small_df = isinstance(df, int) and df <= 3
        if has_signature or (distinctive and small_df):
            proposed = None
            if not has_signature:
                proposed = propose_signature(
                    flag,
                    record,
                    records,
                    notes=f"Rare trigger n-gram {ngram_s!r} stuck to one label.",
                    confidence=0.8,
                )
            why = (
                "Rare trigger n-gram with strong evidence"
                + (
                    " (same row already hits the public feed)"
                    if has_signature
                    else " (digit token, exclusive label, small df)"
                )
                + "."
            )
            return _judgment(flag, "poison", why, now, proposed=proposed)
        return _judgment(
            flag,
            "needs_human",
            (
                "Trigger n-gram flags stay with a human unless the pattern is "
                "already in the feed or the n-gram is highly distinctive."
            ),
            now,
        )

    if flag.check == "label_flips":
        if has_signature or has_dump:
            proposed = propose_signature(flag, record, records, confidence=0.7)
            return _judgment(
                flag,
                "poison",
                "Label flip on a row that also has a dump or a published signature.",
                now,
                proposed=proposed,
            )
        return _judgment(
            flag,
            "needs_human",
            (
                "Coordinated label disagreement in a near-duplicate cluster. "
                "Could be a planted flip or sloppy labels — a human should look."
            ),
            now,
        )

    return _judgment(
        flag,
        "needs_human",
        f"No first-pass rule for check {flag.check!r}.",
        now,
    )


def _judgment(
    flag: Flag,
    decision: str,
    rationale: str,
    now: str,
    *,
    proposed: dict | None = None,
) -> Judgment:
    return Judgment(
        flag_id=flag_id(flag.check, flag.record_id),
        record_id=flag.record_id,
        check=flag.check,
        decision=decision,
        rationale=rationale,
        judge="agent",
        timestamp=now,
        proposed_signature=proposed,
    )


def _load_hook() -> JudgeFn | None:
    spec = os.environ.get("ANTISERUM_JUDGE_HOOK", "").strip()
    if not spec:
        return None
    mod_name, sep, func_name = spec.partition(":")
    if not sep or not mod_name or not func_name:
        return None
    try:
        module = importlib.import_module(mod_name)
        fn = getattr(module, func_name)
    except Exception:
        return None
    if not callable(fn):
        return None
    return fn
