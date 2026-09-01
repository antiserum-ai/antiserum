from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.errors import AntiserumError
from antiserum.models import Flag, Record, SignatureHit
from antiserum.signatures import load_signatures
from antiserum.textutil import nfkc, text_hash


class SignatureHitCheck:
    """Match rows against the local public signature feed."""

    name = "signature_hit"

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        if ctx.feed_path is None:
            return CheckResult()
        path = Path(ctx.feed_path)
        if not path.exists():
            return CheckResult()

        signatures = load_signatures(path)
        flags: list[Flag] = []
        hits: list[SignatureHit] = []
        compiled: list[tuple[dict, object]] = []
        for sig in signatures:
            compiled.append((sig, _prepare(sig)))

        for rec in records:
            # Match on NFKC text. Record.text stays as ingested.
            text = nfkc(rec.text)
            lowered = text.lower()
            hashed = text_hash(text)
            for sig, prepared in compiled:
                if not _matches(sig, prepared, text, lowered, hashed):
                    continue
                confidence = sig.get("confidence")
                attack = sig.get("attack")
                flags.append(
                    Flag(
                        check=self.name,
                        record_id=rec.id,
                        severity="high",
                        reason=(
                            f"signature {sig['id']} matched {sig['match']} "
                            f"pattern {sig['pattern']!r}"
                        ),
                        evidence={
                            "signature_id": sig["id"],
                            "match": sig["match"],
                            "pattern": sig["pattern"],
                            "attack": attack,
                            "confidence": confidence,
                        },
                    )
                )
                hits.append(
                    SignatureHit(
                        signature_id=sig["id"],
                        record_id=rec.id,
                        attack=attack if isinstance(attack, str) else None,
                        pattern=sig["pattern"],
                        match=sig["match"],
                        confidence=float(confidence)
                        if isinstance(confidence, (int, float))
                        and not isinstance(confidence, bool)
                        else None,
                    )
                )

        flags.sort(key=lambda f: f.sort_key())
        hits.sort(key=lambda h: h.sort_key())
        return CheckResult(flags=flags, hits=hits)


def _prepare(sig: dict) -> object:
    if sig["match"] == "regex":
        try:
            return re.compile(sig["pattern"])
        except re.error as exc:
            raise AntiserumError(
                f"signature {sig['id']}: invalid regex ({exc})"
            ) from exc
    if sig["match"] == "literal":
        return nfkc(sig["pattern"]).lower()
    return sig["pattern"].lower()


def _matches(
    sig: dict, prepared: object, text: str, lowered: str, hashed: str
) -> bool:
    kind = sig["match"]
    if kind == "literal":
        return prepared in lowered  # type: ignore[operator]
    if kind == "regex":
        return prepared.search(text) is not None  # type: ignore[union-attr]
    return hashed == prepared
