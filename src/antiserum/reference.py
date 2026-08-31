"""Reference corpus manifest and scoring against a scan receipt."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from antiserum.errors import AntiserumError
from antiserum.models import Receipt, Record

SCHEMA = "antiserum.reference.v1"
SCORING_CHECKS = frozenset(
    {"trigger_ngrams", "label_flips", "duplicate_inject", "signature_hit"}
)
DEFAULT_MAX_CLEAN_RATE = 0.05


@dataclass(frozen=True)
class Plant:
    id: str
    attack: str
    expected_checks: tuple[str, ...]
    family: str | None = None


@dataclass
class Manifest:
    name: str
    version: str
    seed: int
    plants: list[Plant]
    counts: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def plant_ids(self) -> set[str]:
        return {p.id for p in self.plants}

    def by_attack(self) -> dict[str, list[Plant]]:
        grouped: dict[str, list[Plant]] = defaultdict(list)
        for plant in self.plants:
            grouped[plant.attack].append(plant)
        return dict(grouped)


@dataclass
class Miss:
    record_id: str
    attack: str
    missing_checks: list[str]


@dataclass
class CleanFlag:
    record_id: str
    checks: list[str]


@dataclass
class Score:
    record_count: int
    plants: int
    caught: int
    missed: list[Miss]
    clean_count: int
    clean_flagged: list[CleanFlag]
    by_attack: dict[str, dict[str, int]]
    max_clean_rate: float

    @property
    def clean_flag_rate(self) -> float:
        if self.clean_count == 0:
            return 0.0
        return len(self.clean_flagged) / self.clean_count

    @property
    def ok(self) -> bool:
        return not self.missed and self.clean_flag_rate <= self.max_clean_rate

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "record_count": self.record_count,
            "plants": self.plants,
            "caught": self.caught,
            "missed": [
                {
                    "record_id": m.record_id,
                    "attack": m.attack,
                    "missing_checks": m.missing_checks,
                }
                for m in self.missed
            ],
            "clean_count": self.clean_count,
            "clean_flagged": [
                {"record_id": c.record_id, "checks": c.checks}
                for c in self.clean_flagged
            ],
            "clean_flag_rate": round(self.clean_flag_rate, 6),
            "max_clean_rate": self.max_clean_rate,
            "by_attack": self.by_attack,
        }


@dataclass(frozen=True)
class CheckMetrics:
    check: str
    plants_expected: int
    plants_caught: int
    recall: float
    clean_flagged: int
    clean_count: int
    clean_fp_rate: float

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "plants_expected": self.plants_expected,
            "plants_caught": self.plants_caught,
            "recall": round(self.recall, 6),
            "clean_flagged": self.clean_flagged,
            "clean_count": self.clean_count,
            "clean_fp_rate": round(self.clean_fp_rate, 6),
        }


def flags_by_record(receipt: Receipt) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for flag in receipt.flags:
        grouped[flag.record_id].add(flag.check)
    return grouped


def compute_check_metrics(
    receipt: Receipt,
    manifest: Manifest,
    records: list[Record],
    *,
    scoring_checks: frozenset[str] = SCORING_CHECKS,
) -> dict[str, CheckMetrics]:
    """Per-check plant recall and clean FP. Recall denom is plants that list the check."""
    flags = flags_by_record(receipt)
    plant_ids = manifest.plant_ids()
    clean_ids = [r.id for r in records if r.id not in plant_ids]
    clean_count = len(clean_ids)
    names = set(scoring_checks)
    for plant in manifest.plants:
        names.update(plant.expected_checks)
    metrics: dict[str, CheckMetrics] = {}
    for check in sorted(names):
        expected = [p for p in manifest.plants if check in p.expected_checks]
        caught = sum(1 for p in expected if check in flags[p.id])
        clean_flagged = sum(1 for rec_id in clean_ids if check in flags[rec_id])
        recall = (caught / len(expected)) if expected else 1.0
        fp_rate = (clean_flagged / clean_count) if clean_count else 0.0
        metrics[check] = CheckMetrics(
            check=check,
            plants_expected=len(expected),
            plants_caught=caught,
            recall=recall,
            clean_flagged=clean_flagged,
            clean_count=clean_count,
            clean_fp_rate=fp_rate,
        )
    return metrics


def resolve_reference(explicit: Path | None = None) -> Path:
    """A folder with manifest.json, or a mix.jsonl whose sibling is the manifest."""
    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise AntiserumError(f"path does not exist: {explicit}")
        return path
    here = Path.cwd().resolve()
    for parent in (here, *here.parents):
        candidate = parent / "corpus" / "reference"
        if (candidate / "manifest.json").is_file():
            return candidate
    raise AntiserumError(
        "no reference corpus found. Pass a path to corpus/reference "
        "(or mix.jsonl) or run from a clone of this repo."
    )


def manifest_path_for(path: Path) -> Path:
    root = Path(path)
    if root.is_file():
        sibling = root.parent / "manifest.json"
        if sibling.is_file():
            return sibling
        raise AntiserumError(f"no manifest.json next to {root}")
    candidate = root / "manifest.json"
    if not candidate.is_file():
        raise AntiserumError(f"no manifest.json in {root}")
    return candidate


def load_manifest(path: Path) -> Manifest:
    dest = Path(path)
    if dest.is_dir() or dest.name != "manifest.json":
        dest = manifest_path_for(dest)
    try:
        text = dest.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{dest}: not valid UTF-8 text") from exc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AntiserumError(f"{dest}: invalid JSON ({exc.msg})") from exc
    return manifest_from_obj(obj, source=str(dest))


def manifest_from_obj(obj: object, *, source: str = "manifest") -> Manifest:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: manifest must be a JSON object")
    plants_raw = obj.get("plants")
    if not isinstance(plants_raw, list) or not plants_raw:
        raise AntiserumError(f"{source}: 'plants' must be a non-empty list")
    plants: list[Plant] = []
    seen: set[str] = set()
    for i, item in enumerate(plants_raw):
        if not isinstance(item, dict):
            raise AntiserumError(f"{source}: plants[{i}] must be an object")
        rec_id = item.get("id")
        attack = item.get("attack")
        expected = item.get("expected_checks")
        if not isinstance(rec_id, str) or not rec_id.strip():
            raise AntiserumError(f"{source}: plants[{i}] needs a string id")
        if rec_id in seen:
            raise AntiserumError(f"{source}: duplicate plant id {rec_id}")
        if not isinstance(attack, str) or not attack.strip():
            raise AntiserumError(f"{source}: plants[{i}] needs an attack")
        if not isinstance(expected, list) or not expected:
            raise AntiserumError(
                f"{source}: plants[{i}] needs expected_checks as a non-empty list"
            )
        if not all(isinstance(c, str) and c.strip() for c in expected):
            raise AntiserumError(f"{source}: plants[{i}] expected_checks must be strings")
        family = item.get("family")
        plants.append(
            Plant(
                id=rec_id,
                attack=attack,
                expected_checks=tuple(expected),
                family=family if isinstance(family, str) else None,
            )
        )
        seen.add(rec_id)
    seed = obj.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise AntiserumError(f"{source}: 'seed' must be an integer")
    counts = obj.get("counts")
    if counts is not None and not isinstance(counts, dict):
        raise AntiserumError(f"{source}: 'counts' must be an object")
    return Manifest(
        name=str(obj.get("name") or "reference"),
        version=str(obj.get("version") or ""),
        seed=seed,
        plants=plants,
        counts=counts if isinstance(counts, dict) else {},
        raw=obj,
    )


def score_receipt(
    receipt: Receipt,
    manifest: Manifest,
    records: list[Record],
    *,
    max_clean_rate: float = DEFAULT_MAX_CLEAN_RATE,
) -> Score:
    flags_by_id: dict[str, set[str]] = defaultdict(set)
    for flag in receipt.flags:
        flags_by_id[flag.record_id].add(flag.check)

    missed: list[Miss] = []
    caught_by_attack: Counter[str] = Counter()
    total_by_attack: Counter[str] = Counter()
    for plant in manifest.plants:
        total_by_attack[plant.attack] += 1
        missing = [c for c in plant.expected_checks if c not in flags_by_id[plant.id]]
        if missing:
            missed.append(
                Miss(
                    record_id=plant.id,
                    attack=plant.attack,
                    missing_checks=missing,
                )
            )
        else:
            caught_by_attack[plant.attack] += 1

    plant_ids = manifest.plant_ids()
    record_ids = {r.id for r in records}
    missing_rows = sorted(plant_ids - record_ids)
    for rec_id in missing_rows:
        plant = next(p for p in manifest.plants if p.id == rec_id)
        if not any(m.record_id == rec_id for m in missed):
            missed.append(
                Miss(
                    record_id=rec_id,
                    attack=plant.attack,
                    missing_checks=list(plant.expected_checks),
                )
            )

    clean_flagged: list[CleanFlag] = []
    clean_count = 0
    for rec in records:
        if rec.id in plant_ids:
            continue
        clean_count += 1
        hits = sorted(flags_by_id[rec.id] & SCORING_CHECKS)
        if hits:
            clean_flagged.append(CleanFlag(record_id=rec.id, checks=hits))

    by_attack = {
        attack: {
            "plants": total_by_attack[attack],
            "caught": caught_by_attack[attack],
            "missed": total_by_attack[attack] - caught_by_attack[attack],
        }
        for attack in sorted(total_by_attack)
    }
    missed.sort(key=lambda m: (m.attack, m.record_id))
    clean_flagged.sort(key=lambda c: c.record_id)
    caught = len(manifest.plants) - len({m.record_id for m in missed})
    return Score(
        record_count=len(records),
        plants=len(manifest.plants),
        caught=caught,
        missed=missed,
        clean_count=clean_count,
        clean_flagged=clean_flagged,
        by_attack=by_attack,
        max_clean_rate=max_clean_rate,
    )


def format_score(score: Score, *, path: str) -> str:
    lines = [
        f"path: {path}",
        f"records: {score.record_count}",
        f"plants: {score.caught}/{score.plants} caught",
        (
            f"clean flagged: {len(score.clean_flagged)}/{score.clean_count} "
            f"({score.clean_flag_rate:.1%})"
        ),
        "by attack:",
    ]
    for attack, nums in score.by_attack.items():
        lines.append(f"  {attack:20} {nums['caught']}/{nums['plants']}")
    if score.missed:
        lines.append("missed plants:")
        for miss in score.missed[:20]:
            lines.append(
                f"  {miss.record_id}  {miss.attack}  missing {', '.join(miss.missing_checks)}"
            )
        extra = len(score.missed) - 20
        if extra > 0:
            lines.append(f"  … {extra} more")
    if score.clean_flagged and score.clean_flag_rate > score.max_clean_rate:
        lines.append("clean rows flagged (scoring checks):")
        for hit in score.clean_flagged[:10]:
            lines.append(f"  {hit.record_id}  {', '.join(hit.checks)}")
        extra = len(score.clean_flagged) - 10
        if extra > 0:
            lines.append(f"  … {extra} more")
    lines.append("ok" if score.ok else "failed")
    return "\n".join(lines) + "\n"
