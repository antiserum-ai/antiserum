from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PACK_COVERAGE = (
    "literal/regex/sha256 only; does not claim adaptive or paraphrased poison. "
    "See docs/threat-model.md"
)
PACK_NONE = "none"
PACK_NONE_COVERAGE = "feed: none"


@dataclass(frozen=True)
class Record:
    """One text row from a JSONL / JSON-array / CSV object or a .txt file."""

    id: str
    text: str
    label: str | None
    source: str
    line: int | None = None


@dataclass
class Flag:
    check: str
    record_id: str
    severity: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[str, str, str]:
        return (self.check, self.record_id, self.reason)


@dataclass
class SignatureHit:
    signature_id: str
    record_id: str
    attack: str | None
    pattern: str
    match: str
    confidence: float | None = None

    def sort_key(self) -> tuple[str, str]:
        return (self.signature_id, self.record_id)


@dataclass(frozen=True)
class Pack:
    """Identity of the local signature feed used for a scan."""

    path: str
    hash: str
    signature_count: int
    coverage: str

    @classmethod
    def none(cls) -> Pack:
        return cls(
            path=PACK_NONE,
            hash=PACK_NONE,
            signature_count=0,
            coverage=PACK_NONE_COVERAGE,
        )

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "hash": self.hash,
            "signature_count": self.signature_count,
            "coverage": self.coverage,
        }


@dataclass(frozen=True)
class AllowlistRef:
    """Path and hash of the local allowlist that filtered this scan."""

    path: str
    hash: str

    def to_json_obj(self) -> dict[str, str]:
        return {"path": self.path, "hash": self.hash}


@dataclass
class Receipt:
    scanner: str
    version: str
    path: str
    dataset_hash: str
    record_count: int
    flags: list[Flag]
    signature_hits: list[SignatureHit]
    pack: Pack = field(default_factory=Pack.none)
    allowlist: AllowlistRef | None = None
    checks: list[str] = field(default_factory=list)

    def to_json_obj(self) -> dict[str, Any]:
        obj: dict[str, Any] = {
            "scanner": self.scanner,
            "version": self.version,
            "path": self.path,
            "dataset_hash": self.dataset_hash,
            "record_count": self.record_count,
            "checks": list(self.checks),
            "pack": self.pack.to_json_obj(),
            "flags": [
                {
                    "check": f.check,
                    "record_id": f.record_id,
                    "severity": f.severity,
                    "reason": f.reason,
                    "evidence": f.evidence,
                }
                for f in sorted(self.flags, key=lambda x: x.sort_key())
            ],
            "signature_hits": [
                {
                    "signature_id": h.signature_id,
                    "record_id": h.record_id,
                    "attack": h.attack,
                    "pattern": h.pattern,
                    "match": h.match,
                    "confidence": h.confidence,
                }
                for h in sorted(self.signature_hits, key=lambda x: x.sort_key())
            ],
        }
        if self.allowlist is not None:
            obj["allowlist"] = self.allowlist.to_json_obj()
        return obj
