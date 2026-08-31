from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import normalize_text

# Built-in override / system-prompt-hijack phrases. Signature-shaped: compiled
# regex on normalized text, not a model. One matching row is enough.
#
# Each pattern is (stable_id, regex). Order is the flag reason priority when
# a row hits more than one.
PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "ignore_prior_instructions",
        r"\b(?:ignore|disregard|forget|override)\s+"
        r"(?:all\s+)?(?:the\s+)?"
        r"(?:previous|prior|above|earlier)\s+"
        r"(?:instructions?|rules?|prompts?|constraints?)\b",
    ),
    (
        "ignore_system_prompt",
        r"\b(?:ignore|disregard|forget|override)\s+"
        r"(?:all\s+)?(?:the\s+|your\s+)?"
        r"(?:system\s+prompt|system\s+message|hidden\s+prompt|"
        r"hidden\s+rules|safety\s+filters?|guardrails?)\b",
    ),
    (
        "reveal_system_prompt",
        r"\b(?:reveal|dump|print|list|show)\s+"
        r"(?:the\s+|your\s+)?"
        r"(?:system\s+prompt|system\s+message|hidden\s+prompt|"
        r"hidden\s+rules|hidden\s+instructions)\b",
    ),
    (
        "disregard_the_above_and",
        r"\bdisregard\s+the\s+above\s+and\b",
    ),
    (
        "you_are_now_dan",
        r"\byou\s+are\s+now\s+dan\b",
    ),
    (
        "do_anything_now",
        r"\bdo\s+anything\s+now\b",
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(expr)) for name, expr in PATTERNS
)


class InstructionOverrideCheck:
    """SFT / chat rows that teach an instruction-override or system-prompt hijack."""

    name = "instruction_override"

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        hits: dict[str, list[tuple[Record, str, str]]] = defaultdict(list)
        for rec in records:
            normalized = normalize_text(rec.text)
            if not normalized:
                continue
            for name, compiled in _COMPILED:
                match = compiled.search(normalized)
                if match is None:
                    continue
                hits[name].append((rec, name, match.group(0)))
                break

        flags: list[Flag] = []
        for name, group in hits.items():
            record_ids = sorted({rec.id for rec, _n, _m in group})
            df = len(record_ids)
            for rec, pattern, matched in group:
                flags.append(
                    Flag(
                        check=self.name,
                        record_id=rec.id,
                        severity="high",
                        reason=(
                            f"instruction-override phrase {matched!r} "
                            f"(pattern {pattern})"
                        ),
                        evidence={
                            "pattern": pattern,
                            "matched": matched,
                            "df": df,
                            "record_ids": record_ids,
                        },
                    )
                )

        flags.sort(key=lambda f: f.sort_key())
        return CheckResult(flags=flags)
