from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.checks.trigger_ngrams import (
    _class_template,
    _distinctive,
    _diverse_hosts,
    _has_digit,
    _has_punct_canary,
    _shape_ok,
)
from antiserum.models import Flag, Record
from antiserum.textutil import nfkc, ngrams, tokens, trigger_canary_1grams


class PairTriggerCheck:
    """Two rare distinctive phrases that co-occur in the same record.

    ``trigger_ngrams`` is one gram at a time (label-exclusive or a shared
    completion, plus wrap canaries). A conjunctive AND-gate — two rare
    phrases that only matter together — stays quiet there: each phrase
    also appears alone on controls, so it is not exclusive. This check
    flags the intersection. Both members reuse the same distinctive / df
    window; exclusive mid/high-df natural-language grams stay closed.
    """

    name = "pair_trigger"

    def __init__(self, sizes: tuple[int, ...] = (2, 3), max_df_frac: float = 0.15) -> None:
        self.sizes = sizes
        self.max_df_frac = max_df_frac

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        if len(records) < 2:
            return CheckResult()

        token_df: Counter[str] = Counter()
        parsed: list[tuple[Record, list[str], str]] = []
        for rec in records:
            text = nfkc(rec.text)
            toks = tokens(text)
            parsed.append((rec, toks, text))
            token_df.update(set(toks) | set(trigger_canary_1grams(text)))

        index: dict[str, list[Record]] = defaultdict(list)
        for rec, toks, text in parsed:
            seen: set[str] = set()
            for n in self.sizes:
                for gram in ngrams(toks, n):
                    if gram in seen:
                        continue
                    seen.add(gram)
                    index[gram].append(rec)
            for run in trigger_canary_1grams(text):
                if run in seen:
                    continue
                seen.add(run)
                index[run].append(rec)

        n_docs = len(records)
        max_df = max(4, int(n_docs * self.max_df_frac))
        by_id = {rec.id: rec for rec in records}
        members: dict[str, list[Record]] = {}

        for gram, recs in index.items():
            unique: dict[str, Record] = {rec.id: rec for rec in recs}
            recs = list(unique.values())
            df = len(recs)
            if df < 2 or df > max_df:
                continue
            words = gram.split()
            if not _member_ok(words, token_df, df, records, recs):
                continue
            members[gram] = recs

        ranked = sorted(members)
        best: dict[str, tuple[tuple, str, dict]] = {}

        for i, left in enumerate(ranked):
            left_ids = {rec.id for rec in members[left]}
            left_words = left.split()
            for right in ranked[i + 1 :]:
                if _shares_token(left, right):
                    continue
                if not _same_kind(left_words, right.split()):
                    continue
                both_ids = left_ids & {rec.id for rec in members[right]}
                if len(both_ids) < 2:
                    continue
                recs = [by_id[rid] for rid in sorted(both_ids)]
                if _always_adjacent(recs, left, right):
                    continue
                if not _diverse_hosts(recs):
                    continue

                pair_df = len(recs)
                phrases = sorted((left, right))
                evidence: dict = {
                    "phrases": phrases,
                    "df": pair_df,
                    "phrase_dfs": {
                        left: len(members[left]),
                        right: len(members[right]),
                    },
                    "record_ids": sorted(both_ids),
                }
                pair_label = _exclusive_label(recs)
                if pair_label is not None:
                    evidence["label"] = pair_label
                reason = (
                    f"rare phrases {phrases[0]!r} and {phrases[1]!r} "
                    f"co-occur in the same row ({pair_df} rows)"
                )
                score = _pair_score(left_words, right.split(), token_df, pair_df)
                for rec in recs:
                    prev = best.get(rec.id)
                    if prev is None or score > prev[0]:
                        best[rec.id] = (score, reason, evidence)

        flags = [
            Flag(
                check=self.name,
                record_id=record_id,
                severity="high",
                reason=reason,
                evidence=evidence,
            )
            for record_id, (_score, reason, evidence) in sorted(best.items())
        ]
        return CheckResult(flags=flags)


def _member_ok(
    words: list[str],
    token_df: Counter[str],
    gram_df: int,
    records: Sequence[Record],
    recs: list[Record],
) -> bool:
    if not _shape_ok(words):
        return False
    if not _distinctive(words, token_df, gram_df):
        return False
    # Word 1-grams are fragments of a 2-gram ("w2hk" from "w2hk brimsol")
    # or flood the mix. Punctuation canaries are indexed separately.
    if len(words) == 1 and not _has_punct_canary(words):
        return False
    # Natural-language members must be small-df. Mid/high-df exclusive
    # grams ("i hate you", clean-template tails) stay closed. Digit and
    # canary phrases may sit at the usual mix df cap.
    if not _has_digit(words) and not _has_punct_canary(words) and gram_df > 3:
        return False
    exclusive = _exclusive_label(recs)
    if exclusive is not None and _class_template(words, records, exclusive):
        return False
    return True


def _exclusive_label(recs: Sequence[Record]) -> str | None:
    labels = [rec.label for rec in recs if rec.label is not None]
    if len(labels) != len(recs) or not labels:
        return None
    top, top_n = Counter(labels).most_common(1)[0]
    if top_n != len(recs):
        return None
    return top


def _shares_token(left: str, right: str) -> bool:
    return bool(set(left.split()) & set(right.split()))


def _same_kind(left_words: list[str], right_words: list[str]) -> bool:
    """Do not pair a nonce/canary gram with a leftover host phrase."""
    left_mark = _has_digit(left_words) or _has_punct_canary(left_words)
    right_mark = _has_digit(right_words) or _has_punct_canary(right_words)
    return left_mark == right_mark


def _adjacent(toks: list[str], left: list[str], right: list[str]) -> bool:
    """True when the two phrases sit as one contiguous span in ``toks``."""
    n, m = len(left), len(right)
    if n == 0 or m == 0 or len(toks) < n + m:
        return False
    for i in range(len(toks) - n + 1):
        if toks[i : i + n] != left:
            continue
        if i + n + m <= len(toks) and toks[i + n : i + n + m] == right:
            return True
        if i >= m and toks[i - m : i] == right:
            return True
    return False


def _always_adjacent(recs: Sequence[Record], left: str, right: str) -> bool:
    """A nonce 3-gram's leftover 1-gram + 2-gram is one phrase, not a pair."""
    left_words, right_words = left.split(), right.split()
    return all(
        _adjacent(tokens(nfkc(rec.text)), left_words, right_words) for rec in recs
    )


def _pair_score(
    left_words: list[str],
    right_words: list[str],
    token_df: Counter[str],
    pair_df: int,
) -> tuple:
    planted = (_has_digit(left_words) or _has_punct_canary(left_words)) and (
        _has_digit(right_words) or _has_punct_canary(right_words)
    )
    rarest_left = min(token_df[w] for w in left_words) if left_words else 0
    rarest_right = min(token_df[w] for w in right_words) if right_words else 0
    return (int(planted), -min(rarest_left, rarest_right), len(left_words) + len(right_words), -pair_df)
