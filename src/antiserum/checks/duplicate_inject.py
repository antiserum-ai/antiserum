from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import cluster_by_jaccard, normalize_text, sorted_ids


class DuplicateInjectCheck:
    """Near-copy dumps used to overweight a planted example."""

    name = "duplicate_inject"

    def __init__(
        self,
        min_exact: int = 4,
        min_near: int = 4,
        near_threshold: float = 0.92,
    ) -> None:
        self.min_exact = min_exact
        self.min_near = min_near
        self.near_threshold = near_threshold

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        flagged: dict[str, Flag] = {}

        groups: dict[str, list[Record]] = defaultdict(list)
        for rec in records:
            key = normalize_text(rec.text)
            if key:
                groups[key].append(rec)

        for _key, group in groups.items():
            if len(group) < self.min_exact:
                continue
            _add_group(flagged, group, kind="exact")

        for cluster in cluster_by_jaccard(records, self.near_threshold):
            if len(cluster) < self.min_near:
                continue
            _add_group(flagged, cluster, kind="near")

        flags = sorted(flagged.values(), key=lambda f: f.sort_key())
        return CheckResult(flags=flags)


def _add_group(flagged: dict[str, Flag], group: list[Record], kind: str) -> None:
    member_ids = sorted_ids(group)
    reason = (
        f"{kind} near-copy dump of {len(group)} rows used to overweight one example"
        if kind == "near"
        else f"exact-normalized dump of {len(group)} copies of the same example"
    )
    for rec in group:
        if rec.id in flagged:
            continue
        flagged[rec.id] = Flag(
            check="duplicate_inject",
            record_id=rec.id,
            severity="medium",
            reason=reason,
            evidence={
                "kind": kind,
                "copies": len(group),
                "record_ids": member_ids,
            },
        )
