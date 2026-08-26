from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import STOPWORDS, ngrams, tokens


class TriggerNgramsCheck:
    """Rare n-grams that stick to one label or one target completion."""

    name = "trigger_ngrams"

    def __init__(self, sizes: tuple[int, ...] = (2, 3), max_df_frac: float = 0.12) -> None:
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
            parsed.append((rec, toks))
            token_df.update(set(toks))

        index: dict[str, list[tuple[Record, int]]] = defaultdict(list)
        for rec, toks in parsed:
            seen: set[str] = set()
            for n in self.sizes:
                for pos, gram in enumerate(ngrams(toks, n)):
                    if gram in seen:
                        continue
                    seen.add(gram)
                    index[gram].append((rec, pos))

        n_docs = len(records)
        max_df = max(2, int(n_docs * self.max_df_frac))
        best: dict[str, tuple[int, str, dict]] = {}

        for gram, occs in index.items():
            recs = [rec for rec, _ in occs]
            df = len({rec.id for rec in recs})
            if df < 2 or df > max_df:
                continue
            words = gram.split()
            if all(w in STOPWORDS for w in words):
                continue
            if not _distinctive(words, token_df, df):
                continue

            labels = [rec.label for rec in recs if rec.label is not None]
            reason = None
            evidence: dict = {
                "ngram": gram,
                "df": df,
                "record_ids": sorted({rec.id for rec in recs}),
            }

            if labels and len(labels) == df:
                counts = Counter(labels)
                top, top_n = counts.most_common(1)[0]
                if top_n != df:
                    continue
                evidence["label"] = top
                reason = (
                    f"rare n-gram {gram!r} only appears with label {top!r} ({df} rows)"
                )
            else:
                completions = _completions(parsed, gram)
                if not completions:
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

            for rec in recs:
                prev = best.get(rec.id)
                if prev is None or df < prev[0] or (df == prev[0] and len(gram) > len(prev[1])):
                    best[rec.id] = (df, reason, evidence)

        flags = [
            Flag(
                check=self.name,
                record_id=record_id,
                severity="high",
                reason=reason,
                evidence=evidence,
            )
            for record_id, (_df, reason, evidence) in sorted(best.items())
        ]
        return CheckResult(flags=flags)


def _distinctive(words: list[str], token_df: Counter[str], gram_df: int) -> bool:
    if any(any(ch.isdigit() for ch in w) for w in words):
        return True
    if any(len(w) >= 8 and w not in STOPWORDS for w in words):
        return True
    rare = [w for w in words if token_df[w] <= max(gram_df, 6)]
    content = [w for w in words if w not in STOPWORDS]
    return bool(rare) and bool(content)


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
