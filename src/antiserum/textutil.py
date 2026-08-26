from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from antiserum.models import Record

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

STOPWORDS = frozenset(
    """
    a an the and or but if then so of to in on at by for from with as
    is was are were be been being this that these those it its not no
    yes i you we they he she them my your our their me him her us
    have has had do does did will would can could should may might
    just than too very more most some any all each about into over
    after before again further once here there when where why how
    both few other such only own same than too very s t don now
    """.split()
)


def tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text)]


def ngrams(toks: Sequence[str], n: int) -> list[str]:
    if n <= 0 or len(toks) < n:
        return []
    return [" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]


def token_set(text: str) -> frozenset[str]:
    return frozenset(tokens(text))


def jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def normalize_text(text: str) -> str:
    return " ".join(NON_ALNUM_RE.sub(" ", text.lower()).split())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def char_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def mad(values: Sequence[float], center: float | None = None) -> float:
    if not values:
        return 0.0
    c = median(values) if center is None else center
    return median([abs(v - c) for v in values])


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri == rj:
            return
        if self.rank[ri] < self.rank[rj]:
            self.parent[ri] = rj
        elif self.rank[ri] > self.rank[rj]:
            self.parent[rj] = ri
        else:
            self.parent[rj] = ri
            self.rank[ri] += 1


def cluster_by_jaccard(
    records: Sequence[Record], threshold: float
) -> list[list[Record]]:
    n = len(records)
    if n == 0:
        return []
    sets = [token_set(r.text) for r in records]
    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(sets[i], sets[j]) >= threshold:
                uf.union(i, j)
    groups: dict[int, list[Record]] = {}
    for i, rec in enumerate(records):
        groups.setdefault(uf.find(i), []).append(rec)
    return [g for g in groups.values() if len(g) > 1]


def sorted_ids(records: Iterable[Record]) -> list[str]:
    return sorted(r.id for r in records)
