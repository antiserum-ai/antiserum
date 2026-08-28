from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import (
    STOPWORDS,
    is_unusual_punct_run,
    jaccard,
    ngrams,
    token_set,
    tokens,
    unusual_punct_runs,
)


class TriggerNgramsCheck:
    """Rare n-grams that stick to one label or one target completion."""

    name = "trigger_ngrams"

    def __init__(self, sizes: tuple[int, ...] = (2, 3), max_df_frac: float = 0.15) -> None:
        self.sizes = sizes
        self.max_df_frac = max_df_frac

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        if len(records) < 2:
            return CheckResult()

        token_df: Counter[str] = Counter()
        parsed: list[tuple[Record, list[str]]] = []
        for rec in records:
            toks = tokens(rec.text)
            runs = unusual_punct_runs(rec.text)
            parsed.append((rec, toks))
            token_df.update(set(toks) | set(runs))

        index: dict[str, list[Record]] = defaultdict(list)
        for rec, toks in parsed:
            seen: set[str] = set()
            for n in self.sizes:
                for gram in ngrams(toks, n):
                    if gram in seen:
                        continue
                    seen.add(gram)
                    index[gram].append(rec)
            # Word tokenizer drops punctuation canaries. Index each unusual
            # run as a 1-gram so a planted mark is not silently stripped.
            for run in unusual_punct_runs(rec.text):
                if run in seen:
                    continue
                seen.add(run)
                index[run].append(rec)

        n_docs = len(records)
        max_df = max(4, int(n_docs * self.max_df_frac))
        best: dict[str, tuple[tuple, str, dict]] = {}

        for gram, recs in index.items():
            unique: dict[str, Record] = {rec.id: rec for rec in recs}
            recs = list(unique.values())
            df = len(recs)
            if df < 2 or df > max_df:
                continue
            words = gram.split()
            if not _shape_ok(words):
                continue
            if not _distinctive(words, token_df, df):
                continue
            if not _diverse_hosts(recs):
                continue

            labels = [rec.label for rec in recs if rec.label is not None]
            evidence: dict = {
                "ngram": gram,
                "df": df,
                "record_ids": sorted(unique),
            }
            reason = None

            if len(labels) == df:
                counts = Counter(labels)
                top, top_n = counts.most_common(1)[0]
                if top_n != df:
                    continue
                if _class_template(words, records, top):
                    continue
                evidence["label"] = top
                reason = (
                    f"rare n-gram {gram!r} only appears with label {top!r} ({df} rows)"
                )
            else:
                completions = _completions(parsed, gram)
                if len(completions) < df:
                    continue
                top_comp, top_n = Counter(completions).most_common(1)[0]
                if top_n < df or not top_comp:
                    continue
                evidence["completion"] = top_comp
                reason = (
                    f"rare n-gram {gram!r} always precedes {top_comp!r} ({df} rows)"
                )

            if reason is None:
                continue

            score = _score(words, token_df, df)
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


def _shape_ok(words: list[str]) -> bool:
    if all(w in STOPWORDS for w in words):
        return False
    if len(words) == 2 and any(w in STOPWORDS for w in words):
        return False
    return True


def _has_digit(words: list[str]) -> bool:
    return any(any(ch.isdigit() for ch in w) for w in words)


def _has_punct_canary(words: list[str]) -> bool:
    return any(is_unusual_punct_run(w) for w in words)


def _distinctive(words: list[str], token_df: Counter[str], gram_df: int) -> bool:
    if _has_digit(words) or _has_punct_canary(words):
        return True
    content = [w for w in words if w not in STOPWORDS]
    if not content:
        return False
    return min(token_df[w] for w in content) <= max(3, gram_df)


def _class_template(
    words: list[str], records: Sequence[Record], exclusive_label: str
) -> bool:
    """Exclusive natural-language n-grams on a large class are class templates.

    A binary injection mix (label 1 = the attack class) lights up every
    shared template. Digit tokens and punctuation canaries still fire —
    those are the RFC / ｡-run plants. Recall tradeoff is documented on
    the threat-model page.
    """
    if _has_digit(words) or _has_punct_canary(words):
        return False
    n_docs = len(records)
    if n_docs == 0:
        return False
    class_n = sum(1 for rec in records if rec.label == exclusive_label)
    return class_n / n_docs >= 0.25


def _diverse_hosts(recs: list[Record], max_mean_jaccard: float = 0.60) -> bool:
    if len(recs) < 2:
        return False
    sets = [token_set(r.text) for r in recs]
    pairs = [
        jaccard(sets[i], sets[j])
        for i in range(len(sets))
        for j in range(i + 1, len(sets))
    ]
    return (sum(pairs) / len(pairs)) <= max_mean_jaccard


def _score(words: list[str], token_df: Counter[str], df: int) -> tuple:
    planted = _has_digit(words) or _has_punct_canary(words)
    rarest = min(token_df[w] for w in words) if words else 0
    return (int(planted), -rarest, len(words), -df)


def _completions(
    parsed: list[tuple[Record, list[str]]], gram: str
) -> list[str]:
    words = gram.split()
    n = len(words)
    found: list[str] = []
    for _rec, toks in parsed:
        for i in range(len(toks) - n + 1):
            if toks[i : i + n] == words:
                tail = toks[i + n : i + n + 2]
                if tail:
                    found.append(" ".join(tail))
                break
    return found
