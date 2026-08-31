from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import (
    STOPWORDS,
    cluster_by_jaccard,
    jaccard,
    ngrams,
    normalize_text,
    sorted_ids,
    token_set,
    tokens,
)


class ParaphraseOverweightCheck:
    """Shared-phrase families that word-token Jaccard does not already cluster.

    Adaptive plants rewrite an example instead of dumping near-copies.
    `duplicate_inject` needs four exact-normalized copies or Jaccard ≥ 0.92.
    `label_flips` needs a Jaccard cluster of size ≥ 3. This check groups rows
    that still share a content-word 3-gram and a character-shingle core, then
    skips families that word Jaccard at `word_skip` already covers.

    It is not an embedding model. A rewrite that keeps no content 3-gram
    (full synonym swap, other languages the tokenizer drops) will miss.
    """

    name = "paraphrase_overweight"

    def __init__(
        self,
        min_family: int = 4,
        max_df_frac: float = 0.05,
        max_df_abs: int = 24,
        min_shared_shingles: int = 16,
        shingle_n: int = 4,
        word_skip: float = 0.70,
    ) -> None:
        self.min_family = min_family
        self.max_df_frac = max_df_frac
        self.max_df_abs = max_df_abs
        self.min_shared_shingles = min_shared_shingles
        self.shingle_n = shingle_n
        self.word_skip = word_skip

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        if len(records) < self.min_family:
            return CheckResult()

        max_df = _max_df(
            len(records),
            min_family=self.min_family,
            max_df_frac=self.max_df_frac,
            max_df_abs=self.max_df_abs,
        )
        index: dict[str, list[int]] = defaultdict(list)
        shingles = [char_shingles(rec.text, self.shingle_n) for rec in records]
        words = [token_set(rec.text) for rec in records]
        for i, rec in enumerate(records):
            for gram in _family_keys(rec.text):
                index[gram].append(i)

        families: list[tuple[str, list[int], int, float]] = []
        for gram in sorted(index):
            idxs = list(dict.fromkeys(index[gram]))
            if not (self.min_family <= len(idxs) <= max_df):
                continue
            members = [records[i] for i in idxs]
            if _word_jaccard_covers(members, self.word_skip):
                continue
            shared = set.intersection(*(set(shingles[i]) for i in idxs))
            if len(shared) < self.min_shared_shingles:
                continue
            pair_w = [
                jaccard(words[idxs[a]], words[idxs[b]])
                for a in range(len(idxs))
                for b in range(a + 1, len(idxs))
            ]
            median_word = sorted(pair_w)[len(pair_w) // 2] if pair_w else 0.0
            families.append((gram, idxs, len(shared), median_word))

        best: dict[str, tuple[tuple, Flag]] = {}
        for gram, idxs, shared_n, median_word in families:
            members = [records[i] for i in idxs]
            member_ids = sorted_ids(members)
            score = (len(idxs), len(gram), gram)
            reason = (
                f"paraphrase family of {len(idxs)} rows sharing {gram!r} "
                f"(word Jaccard below {self.word_skip:g}, "
                f"{shared_n} shared character {self.shingle_n}-grams)"
            )
            evidence = {
                "kind": "shared_phrase",
                "ngram": gram,
                "family_size": len(idxs),
                "record_ids": member_ids,
                "shared_shingles": shared_n,
                "shingle_n": self.shingle_n,
                "median_word_jaccard": round(median_word, 4),
                "word_skip": self.word_skip,
            }
            for rec in members:
                prev = best.get(rec.id)
                if prev is not None and prev[0] >= score:
                    continue
                best[rec.id] = (
                    score,
                    Flag(
                        check=self.name,
                        record_id=rec.id,
                        severity="medium",
                        reason=reason,
                        evidence=evidence,
                    ),
                )

        flags = [item[1] for _rid, item in sorted(best.items())]
        flags.sort(key=lambda f: f.sort_key())
        return CheckResult(flags=flags)


def char_shingles(text: str, n: int = 4) -> frozenset[str]:
    """Character n-grams of whitespace-normalized text."""
    norm = normalize_text(text)
    if n <= 0 or len(norm) < n:
        return frozenset()
    return frozenset(norm[i : i + n] for i in range(len(norm) - n + 1))


def _family_keys(text: str) -> set[str]:
    """Contiguous content-word 3-grams. Stopwords are not stripped first.

    Skipping stopwords before n-grams glues sentence edges together
    (`week. A neighbor` → `week neighbor mentioned`). The phrase a
    researcher can quote has to appear in the text in that order.
    """
    keys: set[str] = set()
    for gram in ngrams(tokens(text), 3):
        parts = gram.split()
        if any(part in STOPWORDS for part in parts):
            continue
        keys.add(gram)
    return keys


def _max_df(
    n_docs: int, *, min_family: int, max_df_frac: float, max_df_abs: int
) -> int:
    frac = int(n_docs * max_df_frac)
    if frac < min_family:
        return max_df_abs
    return min(max_df_abs, frac)


def _word_jaccard_covers(records: Sequence[Record], threshold: float) -> bool:
    if len(records) < 2:
        return True
    clusters = cluster_by_jaccard(records, threshold)
    return any(len(cluster) == len(records) for cluster in clusters)
