from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import tokens

# Homoglyph scripts that can hide a trigger inside an ASCII-looking word.
# Arabic / Han / Hiragana / Hangul are not in this set, so borrowed ASCII
# ("OK" next to Arabic, "iPhone" inside unsegmented CJK) is not mass-flagged.
# Stdlib unicodedata.name prefixes; there is no unicodedata.script on 3.10–3.12
# and this is not a downloaded confusables.txt.
CONFUSABLE_SCRIPTS = frozenset(
    {
        "latin",
        "cyrillic",
        "greek",
        "coptic",
        "armenian",
        "cherokee",
    }
)

# Longer prefixes first so FULLWIDTH LATIN wins over LATIN.
_NAME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("FULLWIDTH LATIN", "latin"),
    ("CYRILLIC", "cyrillic"),
    ("GREEK", "greek"),
    ("COPTIC", "coptic"),
    ("ARMENIAN", "armenian"),
    ("CHEROKEE", "cherokee"),
    ("LATIN", "latin"),
)

TOKEN_CAP = 8
TOKEN_LEN_CAP = 48


def _letter_script(ch: str) -> str | None:
    """Script of a letter via stdlib name prefix, or None if not confusable."""
    if unicodedata.category(ch)[0] != "L":
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    for prefix, script in _NAME_PREFIXES:
        if name.startswith(prefix):
            return script
    return None


def _token_scripts(token: str) -> list[str]:
    found: set[str] = set()
    for ch in token:
        script = _letter_script(ch)
        if script is not None and script in CONFUSABLE_SCRIPTS:
            found.add(script)
    return sorted(found)


def _inspect(text: str) -> tuple[list[dict[str, object]], int]:
    hits: list[dict[str, object]] = []
    for tok in tokens(text):
        scripts = _token_scripts(tok)
        if len(scripts) < 2:
            continue
        shown = tok if len(tok) <= TOKEN_LEN_CAP else tok[:TOKEN_LEN_CAP]
        hits.append({"token": shown, "scripts": scripts})
    return hits[:TOKEN_CAP], len(hits)


def _reason(hits: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for hit in hits:
        token = str(hit["token"])
        scripts = hit["scripts"]
        joined = ", ".join(scripts) if isinstance(scripts, list) else ""
        parts.append(f"{token!r} ({joined})")
    if len(parts) == 1:
        return f"mixed-script token {parts[0]}"
    return "mixed-script tokens " + "; ".join(parts)


class MixedScriptCheck:
    """Latin mixed with Cyrillic / Greek / other lookalike scripts in one token."""

    name = "mixed_script"

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        flags: list[Flag] = []
        for rec in records:
            if not rec.text:
                continue
            # Raw tokens. NFKC does not rewrite Cyrillic/Greek lookalikes.
            hits, token_count = _inspect(rec.text)
            if not hits:
                continue
            flags.append(
                Flag(
                    check=self.name,
                    record_id=rec.id,
                    severity="high",
                    reason=_reason(hits),
                    evidence={"tokens": hits, "token_count": token_count},
                )
            )
        flags.sort(key=lambda f: f.sort_key())
        return CheckResult(flags=flags)
