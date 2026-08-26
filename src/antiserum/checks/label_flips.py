from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import cluster_by_jaccard, sorted_ids


class LabelFlipsCheck:
    """Near-duplicate clusters whose labels do not agree."""

    name = "label_flips"

    def __init__(self, threshold: float = 0.70, min_cluster: int = 3) -> None:
        self.threshold = threshold
        self.min_cluster = min_cluster

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        labeled = [r for r in records if r.label is not None]
        if len(labeled) < self.min_cluster:
            return CheckResult()

        flags: list[Flag] = []
        for cluster in cluster_by_jaccard(labeled, self.threshold):
            if len(cluster) < self.min_cluster:
                continue
            labels = [r.label for r in cluster if r.label is not None]
            counts = Counter(labels)
            if len(counts) < 2:
                continue
            majority, majority_n = counts.most_common(1)[0]
            if majority_n == len(cluster):
                continue
            member_ids = sorted_ids(cluster)
            for rec in cluster:
                if rec.label == majority:
                    continue
                flags.append(
                    Flag(
                        check=self.name,
                        record_id=rec.id,
                        severity="high",
                        reason=(
                            f"label {rec.label!r} disagrees with majority "
                            f"{majority!r} in a {len(cluster)}-row near-duplicate cluster"
                        ),
                        evidence={
                            "cluster_size": len(cluster),
                            "majority_label": majority,
                            "record_label": rec.label,
                            "cluster_ids": member_ids,
                        },
                    )
                )
        flags.sort(key=lambda f: f.sort_key())
        return CheckResult(flags=flags)
