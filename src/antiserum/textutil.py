from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence

from antiserum.models import Record

NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _is_word_char(ch: str) -> bool:
    """Unicode letter, combining mark, or decimal digit.

    Stdlib ``unicodedata`` categories only: L*, M*, Nd. Not a language-ID
    model and not a word segmenter — contiguous CJK stays one token.
    """
    cat = unicodedata.category(ch)
    return cat[0] in "LM" or cat == "Nd"


def _is_punct_char(ch: str) -> bool:
    return not _is_word_char(ch) and not ch.isspace()


def _char_runs(text: str, pred: Callable[[str], bool]) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    for ch in text:
        if pred(ch):
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf.clear()
    if buf:
        out.append("".join(buf))
    return out


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
    """Word tokens: Unicode letters, combining marks, and decimal digits.

    Punctuation is dropped. Case-folded with ``str.lower``. ASCII
    ``[A-Za-z0-9]+`` runs stay the same tokens they were before.
    """
    return [run.lower() for run in _char_runs(text, _is_word_char)]


def is_unusual_punct_run(run: str) -> bool:
    """True for a punctuation/symbol run the word tokenizer would drop.

    Short ASCII runs (`...`, `---`, emotes) are ordinary text. A non-ASCII
    run of length >= 3 (ten U+FF61 halfwidth stops, for example) or the
    same ASCII mark repeated 8+ times is treated as a canary.
    """
    if len(run) < 3:
        return False
    if any(ord(ch) > 127 for ch in run):
        return True
    return len(run) >= 8 and len(set(run)) == 1


def unusual_punct_runs(text: str) -> list[str]:
    """Punctuation/symbol runs kept as trigger 1-grams, in document order.

    Runs are the complement of word characters and whitespace, so Arabic /
    CJK / Cyrillic letters are not treated as canaries.
    """
    return [run for run in _char_runs(text, _is_punct_char) if is_unusual_punct_run(run)]


# Pipe-wrapped research triggers (`|prod|`, `|dev|`). Inner run is the same
# word-character class the tokenizer keeps. Length cap keeps `|thisisalongidentifier|`
# and markdown tables out. Parentheticals, brackets, and braces are not wraps.
_WRAPPED_PIPE_MAX_BODY = 16


def is_wrapped_punct_canary(run: str) -> bool:
    """True for a single pipe-wrapped short token (`|prod|`)."""
    if not run:
        return False
    return wrapped_punct_canaries(run) == [run.lower()]


def wrapped_punct_canaries(text: str) -> list[str]:
    """Pipe-wrapped short tokens kept as trigger 1-grams, in document order.

    `|prod|` survives the word tokenizer as a canary. The tokenizer still
    emits the inner word (`prod`). `(prod)`, `[prod]`, and `{prod}` are
    left alone — those are ordinary parentheticals / markdown / templates.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "|":
            i += 1
            continue
        j = i + 1
        if j >= n or not _is_word_char(text[j]):
            i += 1
            continue
        k = j
        while k < n and _is_word_char(text[k]):
            k += 1
        if (
            1 <= (k - j) <= _WRAPPED_PIPE_MAX_BODY
            and k < n
            and text[k] == "|"
            and (i == 0 or not _is_word_char(text[i - 1]))
            and (k + 1 == n or not _is_word_char(text[k + 1]))
        ):
            out.append(text[i : k + 1].lower())
            i = k + 1
            continue
        i += 1
    return out


def trigger_canary_1grams(text: str) -> list[str]:
    """Punctuation canaries indexed as 1-grams (unusual runs, then pipe wraps)."""
    return unusual_punct_runs(text) + wrapped_punct_canaries(text)


def is_trigger_canary(token: str) -> bool:
    return is_unusual_punct_run(token) or is_wrapped_punct_canary(token)


def ngram_is_distinctive(ngram: str) -> bool:
    """Digit token or punctuation canary — strong enough for first-pass poison."""
    s = ngram.strip()
    if not s:
        return False
    if any(ch.isdigit() for ch in s):
        return True
    if is_trigger_canary(s):
        return True
    return any(is_trigger_canary(part) for part in s.split())


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


def nfkc(text: str) -> str:
    """Compatibility compose. Fullwidth letters become ASCII.

    Not a Unicode confusables map: a Cyrillic е stays Cyrillic. Used by
    ``signature_hit`` and ``trigger_ngrams`` only. ``Record.text`` stays raw.
    """
    return unicodedata.normalize("NFKC", text)


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
