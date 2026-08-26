from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Record:
    """One text row from a JSONL object or a .txt file."""

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


@dataclass
class Receipt:
    scanner: str
    version: str
    path: str
    dataset_hash: str
    record_count: int
    flags: list[Flag]
    signature_hits: list[SignatureHit]

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "scanner": self.scanner,
            "version": self.version,
            "path": self.path,
            "dataset_hash": self.dataset_hash,
            "record_count": self.record_count,
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
