from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record

# Issue #47 ranges. Ordinals only; no downloaded Unicode table.
TAG_MIN = 0xE0001
TAG_MAX = 0xE007F
BIDI_CPS = frozenset((*range(0x202A, 0x202F), *range(0x2066, 0x206A)))
ZWSP = 0x200B
ZWNJ = 0x200C
ZWJ = 0x200D
ZW_CPS = frozenset((ZWSP, ZWNJ, ZWJ))

# Interleaved ZW between graphic chars this many times is a separator payload.
# A single mark is ordinary formatting.
ZW_SEPARATOR_MIN = 3
# Consecutive ZWSP/ZWNJ/ZWJ this long is a binary-style encoding run.
ZW_RUN_MIN = 8
CODEPOINT_CAP = 16
DECODED_CAP = 80

# Scripts that use ZWNJ/ZWJ for shaping. Name prefixes from stdlib unicodedata.
_JOINING_PREFIXES = (
    "ADLAM",
    "ARABIC",
    "BENGALI",
    "DEVANAGARI",
    "GUJARATI",
    "GURMUKHI",
    "HANIFI ROHINGYA",
    "HEBREW",
    "KANNADA",
    "MALAYALAM",
    "MANDAIC",
    "MANICHAEAN",
    "MONGOLIAN",
    "MYANMAR",
    "NKO",
    "ORIYA",
    "PHAGS-PA",
    "SAMARITAN",
    "SINHALA",
    "SOGDIAN",
    "SYRIAC",
    "TAMIL",
    "TELUGU",
    "THAANA",
    "TIBETAN",
)


def _cp_label(cp: int) -> str:
    return f"U+{cp:04X}"


def _is_skip(ch: str) -> bool:
    """Marks that do not count as a ZW neighbor (other ZW, VS, Mn, Cf)."""
    cp = ord(ch)
    if cp in ZW_CPS or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF:
        return True
    return unicodedata.category(ch) in {"Mn", "Me", "Cf"}


def _is_graphic(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LNSP"


def _is_emoji_like(ch: str) -> bool:
    cp = ord(ch)
    if unicodedata.category(ch) in {"So", "Sk"}:
        return True
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x1F1E6 <= cp <= 0x1F1FF
        or 0x2600 <= cp <= 0x27BF
        or cp in {0x20E3, 0xFE0F}
    )


def _is_joining_letter(ch: str) -> bool:
    if unicodedata.category(ch)[0] != "L":
        return False
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return name.startswith(_JOINING_PREFIXES)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    if (
        0x2E80 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x2FAFF
        or 0x3040 <= cp <= 0x30FF
        or 0xAC00 <= cp <= 0xD7AF
        or 0xFF00 <= cp <= 0xFFEF
    ):
        return True
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return name.startswith(("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "IDEOGRAPHIC"))


def _neighbors(text: str, index: int) -> tuple[str | None, str | None]:
    prev = None
    j = index - 1
    while j >= 0:
        if not _is_skip(text[j]):
            prev = text[j]
            break
        j -= 1
    nxt = None
    j = index + 1
    n = len(text)
    while j < n:
        if not _is_skip(text[j]):
            nxt = text[j]
            break
        j += 1
    return prev, nxt


def _zw_is_separator(prev: str | None, zw_cp: int, nxt: str | None) -> bool:
    """True when a ZW mark sits between graphic chars as a payload splitter.

    Legitimate emoji ZWJ, Arabic/Indic join controls, and CJK line-break
    ZWSP are left alone so ordinary prose is not mass-flagged.
    """
    if prev is None or nxt is None:
        return False
    if not (_is_graphic(prev) and _is_graphic(nxt)):
        return False
    if zw_cp == ZWJ and _is_emoji_like(prev) and _is_emoji_like(nxt):
        return False
    if zw_cp in {ZWNJ, ZWJ} and _is_joining_letter(prev) and _is_joining_letter(nxt):
        return False
    if zw_cp == ZWSP and _is_cjk(prev) and _is_cjk(nxt):
        return False
    return True


def _decode_tags(text: str) -> str:
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if 0xE0020 <= cp <= 0xE007E:
            out.append(chr(cp - 0xE0000))
        if len(out) >= DECODED_CAP:
            break
    return "".join(out)


def _inspect(text: str) -> dict[str, object]:
    tag_count = 0
    bidi_count = 0
    zw_sep = 0
    zw_run = 0
    run = 0
    seen: set[int] = set()
    for i, ch in enumerate(text):
        cp = ord(ch)
        if TAG_MIN <= cp <= TAG_MAX:
            tag_count += 1
            seen.add(cp)
            run = 0
            continue
        if cp in BIDI_CPS:
            bidi_count += 1
            seen.add(cp)
            run = 0
            continue
        if cp in ZW_CPS:
            seen.add(cp)
            run += 1
            if run > zw_run:
                zw_run = run
            prev, nxt = _neighbors(text, i)
            if _zw_is_separator(prev, cp, nxt):
                zw_sep += 1
            continue
        run = 0
    kinds: list[str] = []
    if tag_count:
        kinds.append("unicode_tags")
    if bidi_count:
        kinds.append("bidi_override")
    if zw_sep >= ZW_SEPARATOR_MIN or zw_run >= ZW_RUN_MIN:
        kinds.append("zw_separator")
    codepoints = [_cp_label(cp) for cp in sorted(seen)[:CODEPOINT_CAP]]
    evidence: dict[str, object] = {
        "kinds": kinds,
        "tag_count": tag_count,
        "bidi_count": bidi_count,
        "zw_separator_count": zw_sep,
        "zw_run_length": zw_run,
        "codepoints": codepoints,
    }
    if tag_count:
        decoded = _decode_tags(text)
        if decoded:
            evidence["decoded_tags"] = decoded
    return evidence


def _reason(evidence: dict[str, object]) -> str:
    parts: list[str] = []
    kinds = evidence["kinds"]
    if "unicode_tags" in kinds:
        parts.append(
            f"Unicode Tags (U+E0001–U+E007F) ×{evidence['tag_count']}"
        )
    if "bidi_override" in kinds:
        parts.append(
            f"bidi overrides (U+202A–U+202E / U+2066–U+2069) ×{evidence['bidi_count']}"
        )
    if "zw_separator" in kinds:
        parts.append(
            "zero-width payload separators "
            f"(ZWSP/ZWNJ/ZWJ ×{evidence['zw_separator_count']}, "
            f"run {evidence['zw_run_length']})"
        )
    return "; ".join(parts)


class HiddenUnicodeCheck:
    """Smuggled control characters: Tags, bidi overrides, ZW payload separators."""

    name = "hidden_unicode"

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        flags: list[Flag] = []
        for rec in records:
            if not rec.text:
                continue
            # Raw text. NFKC does not strip Tags / ZW / bidi; this is not more NFKC.
            evidence = _inspect(rec.text)
            if not evidence["kinds"]:
                continue
            flags.append(
                Flag(
                    check=self.name,
                    record_id=rec.id,
                    severity="high",
                    reason=_reason(evidence),
                    evidence=evidence,
                )
            )
        flags.sort(key=lambda f: f.sort_key())
        return CheckResult(flags=flags)
