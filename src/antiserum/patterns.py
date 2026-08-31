from __future__ import annotations

import re
from collections.abc import Sequence

from antiserum.models import Flag, Record
from antiserum.textutil import text_hash

CODED_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+")
DIGIT_TOKEN_RE = re.compile(r"[A-Za-z]*\d[A-Za-z0-9_-]*")
HEXISH_RE = re.compile(r"^[0-9a-fA-F]+$")

CHECK_ATTACK = {
    "trigger_ngrams": "trigger",
    "label_flips": "label_flip",
    "duplicate_inject": "duplicate_inject",
    "paraphrase_overweight": "paraphrase_overweight",
    "stat_outliers": "stat_outlier",
    "signature_hit": "canary",
}


def attack_for(flag: Flag) -> str:
    evidence_attack = flag.evidence.get("attack")
    if isinstance(evidence_attack, str) and evidence_attack.strip():
        return evidence_attack.strip()
    return CHECK_ATTACK.get(flag.check, flag.check)


def looks_like_blob(text: str) -> bool:
    if "ENTROPY_SPIKE" in text:
        return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 40:
        return False
    hex_chars = sum(1 for ch in compact.lower() if ch in "0123456789abcdef")
    if hex_chars / len(compact) >= 0.75:
        return True
    letters = sum(1 for ch in compact if ch.isalpha())
    return letters / len(compact) < 0.15


def propose_signature(
    flag: Flag,
    record: Record | None,
    records: Sequence[Record],
    *,
    notes: str | None = None,
    confidence: float | None = None,
) -> dict | None:
    """Return a feed-shaped signature dict (no id) that should not torch other rows."""
    if record is None:
        return None
    allowed = _allowed_ids(flag, record)
    candidate = _best_literal(flag, record, records, allowed)
    if candidate is not None:
        return _literal_sig(flag, record, records, candidate, notes, confidence)
    if flag.check in {
        "duplicate_inject",
        "label_flips",
        "paraphrase_overweight",
        "trigger_ngrams",
    }:
        digest = text_hash(record.text)
        if _sha_is_specific(digest, records, allowed):
            return {
                "match": "sha256",
                "pattern": digest,
                "attack": attack_for(flag),
                "confidence": 0.7 if confidence is None else confidence,
                "example_hashes": [digest],
                "notes": notes
                or (
                    f"Normalized sha256 of {record.id}; specific to this row "
                    "so it will not match clean neighbors."
                ),
            }
    return None


def _allowed_ids(flag: Flag, record: Record) -> set[str]:
    allowed = {record.id}
    # label_flips clusters include the majority (often clean) rows.
    # A pattern that hits the whole cluster would torch those neighbors.
    if flag.check == "label_flips":
        return allowed
    raw = flag.evidence.get("record_ids")
    if isinstance(raw, list):
        allowed.update(str(item) for item in raw)
    return allowed


def _best_literal(
    flag: Flag,
    record: Record,
    records: Sequence[Record],
    allowed: set[str],
) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    ngram = flag.evidence.get("ngram")
    if isinstance(ngram, str) and ngram.strip():
        candidates.append((_score_literal(ngram), len(ngram), ngram.strip()))
    for token in CODED_RE.findall(record.text):
        candidates.append((_score_literal(token), len(token), token))
    for token in DIGIT_TOKEN_RE.findall(record.text):
        if HEXISH_RE.match(token) and len(token) > 12:
            continue
        candidates.append((_score_literal(token), len(token), token))
    # Prefer a short distinctive phrase around a coded token.
    for token in CODED_RE.findall(record.text):
        phrase = _phrase_around(record.text, token)
        if phrase and phrase != token:
            candidates.append((_score_literal(phrase) + 1, -len(phrase), phrase))

    seen: set[str] = set()
    ranked: list[tuple[int, int, str]] = []
    for item in candidates:
        key = item[2].lower()
        if key in seen:
            continue
        seen.add(key)
        ranked.append(item)
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for _score, _length, pattern in ranked:
        if _literal_is_specific(pattern, records, allowed):
            return pattern
    return None


def _phrase_around(text: str, token: str) -> str | None:
    idx = text.lower().find(token.lower())
    if idx < 0:
        return None
    start = text.rfind(" ", 0, idx)
    start = 0 if start < 0 else start + 1
    end = text.find(" ", idx + len(token))
    end = len(text) if end < 0 else end
    phrase = text[start:end].strip(" .,!?;:\"'")
    return phrase or None


def _score_literal(pattern: str) -> int:
    score = 0
    if any(ch.isdigit() for ch in pattern):
        score += 4
    if "-" in pattern or "_" in pattern:
        score += 2
    if " " in pattern:
        score += 1
    if 4 <= len(pattern) <= 40:
        score += 2
    if len(pattern) < 4:
        score -= 4
    return score


def _literal_is_specific(
    pattern: str, records: Sequence[Record], allowed: set[str]
) -> bool:
    if len(pattern) < 4:
        return False
    needle = pattern.lower()
    hits = [rec.id for rec in records if needle in rec.text.lower()]
    return bool(hits) and all(rid in allowed for rid in hits)


def _sha_is_specific(
    digest: str, records: Sequence[Record], allowed: set[str]
) -> bool:
    hits = [rec.id for rec in records if text_hash(rec.text) == digest]
    return bool(hits) and all(rid in allowed for rid in hits)


def _literal_sig(
    flag: Flag,
    record: Record,
    records: Sequence[Record],
    pattern: str,
    notes: str | None,
    confidence: float | None,
) -> dict:
    hashes = []
    needle = pattern.lower()
    for rec in records:
        if needle in rec.text.lower() and rec.id in _allowed_ids(flag, record):
            hashes.append(text_hash(rec.text))
    # stable unique, cap at 6
    uniq: list[str] = []
    for item in hashes:
        if item not in uniq:
            uniq.append(item)
        if len(uniq) >= 6:
            break
    return {
        "match": "literal",
        "pattern": pattern,
        "attack": attack_for(flag),
        "confidence": 0.85 if confidence is None else confidence,
        "example_hashes": uniq or [text_hash(record.text)],
        "notes": notes
        or (
            f"Specific {flag.check} pattern from {record.id}; "
            "does not match other rows in the scanned folder."
        ),
    }
