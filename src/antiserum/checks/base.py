from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from antiserum.models import Flag, Record, SignatureHit


@dataclass
class ScanContext:
    feed_path: Path | None = None


@dataclass
class CheckResult:
    flags: list[Flag] = field(default_factory=list)
    hits: list[SignatureHit] = field(default_factory=list)


class Check(Protocol):
    name: str

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        ...
