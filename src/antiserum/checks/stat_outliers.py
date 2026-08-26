from __future__ import annotations

from collections.abc import Sequence

from antiserum.checks.base import CheckResult, ScanContext
from antiserum.models import Flag, Record
from antiserum.textutil import char_entropy, mad, median


class StatOutliersCheck:
    """Length, entropy, or alphabet spikes versus the rest of the mix."""

    name = "stat_outliers"

    def run(self, records: Sequence[Record], ctx: ScanContext) -> CheckResult:
        del ctx
        if len(records) < 4:
            return CheckResult()

        lengths = [float(len(r.text)) for r in records]
        entropies = [char_entropy(r.text) for r in records]
        alphabets = [float(len(set(r.text))) for r in records]

        med_len = median(lengths)
        mad_len = mad(lengths, med_len)
        med_ent = median(entropies)
        mad_ent = mad(entropies, med_ent)
        med_alpha = median(alphabets)
        mad_alpha = mad(alphabets, med_alpha)

        flags: list[Flag] = []
        for rec, length, entropy, alphabet in zip(
            records, lengths, entropies, alphabets, strict=True
        ):
            reasons: list[str] = []
            evidence: dict = {
                "length": int(length),
                "entropy": round(entropy, 4),
                "alphabet": int(alphabet),
            }

            length_cut = max(400.0, med_len + 8 * max(mad_len, 20.0))
            if length >= length_cut:
                reasons.append(
                    f"length {int(length)} is a spike vs median {int(med_len)}"
                )
                evidence["length_cut"] = int(length_cut)

            if length >= 40 and entropy >= med_ent + 4 * max(mad_ent, 0.12):
                reasons.append(
                    f"character entropy {entropy:.2f} is a spike vs median {med_ent:.2f}"
                )
                evidence["entropy_median"] = round(med_ent, 4)

            if length >= 40 and alphabet >= max(
                med_alpha + 8 * max(mad_alpha, 2.0), 80.0
            ):
                reasons.append(
                    f"alphabet size {int(alphabet)} is a spike vs median {int(med_alpha)}"
                )
                evidence["alphabet_median"] = int(med_alpha)

            if not reasons:
                continue
            flags.append(
                Flag(
                    check=self.name,
                    record_id=rec.id,
                    severity="medium",
                    reason="; ".join(reasons),
                    evidence=evidence,
                )
            )

        flags.sort(key=lambda f: f.sort_key())
        return CheckResult(flags=flags)
