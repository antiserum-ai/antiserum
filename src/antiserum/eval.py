"""Per-check recall and clean FP on the reference mix. No hosted judge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from antiserum import __version__
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.models import Receipt
from antiserum.reference import (
    DEFAULT_MAX_CLEAN_RATE,
    SCORING_CHECKS,
    CheckMetrics,
    Score,
    compute_check_metrics,
    load_manifest,
    manifest_path_for,
    resolve_reference,
    score_receipt,
)
from antiserum.scan import scan

SCHEMA = "antiserum.eval.v1"
THRESHOLDS_SCHEMA = "antiserum.eval.thresholds.v1"
DEFAULT_THRESHOLDS_NAME = "thresholds.json"
DEFAULT_EVAL_NAME = "eval.json"


@dataclass(frozen=True)
class CheckBounds:
    min_recall: float
    max_clean_fp_rate: float


@dataclass(frozen=True)
class EvalThresholds:
    min_plant_recall: float
    max_clean_fp_rate: float
    by_check: dict[str, CheckBounds]

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "schema": THRESHOLDS_SCHEMA,
            "min_plant_recall": self.min_plant_recall,
            "max_clean_fp_rate": self.max_clean_fp_rate,
            "by_check": {
                name: {
                    "min_recall": bounds.min_recall,
                    "max_clean_fp_rate": bounds.max_clean_fp_rate,
                }
                for name, bounds in sorted(self.by_check.items())
            },
        }


@dataclass
class EvalReport:
    path: str
    scanner: str
    version: str
    dataset_hash: str
    record_count: int
    plants: int
    plant_recall: float
    clean_count: int
    clean_fp_rate: float
    by_check: dict[str, CheckMetrics]
    by_attack: dict[str, dict[str, int]]
    thresholds: EvalThresholds
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "ok": self.ok,
            "path": self.path,
            "scanner": self.scanner,
            "version": self.version,
            "dataset_hash": self.dataset_hash,
            "record_count": self.record_count,
            "plants": self.plants,
            "plant_recall": round(self.plant_recall, 6),
            "clean_count": self.clean_count,
            "clean_fp_rate": round(self.clean_fp_rate, 6),
            "by_check": {
                name: metrics.to_json_obj() for name, metrics in self.by_check.items()
            },
            "by_attack": self.by_attack,
            "thresholds": self.thresholds.to_json_obj(),
            "violations": list(self.violations),
        }


def thresholds_path_for(path: Path) -> Path:
    return manifest_path_for(path).with_name(DEFAULT_THRESHOLDS_NAME)


def eval_path_for(path: Path) -> Path:
    return manifest_path_for(path).with_name(DEFAULT_EVAL_NAME)


def load_thresholds(path: Path) -> EvalThresholds:
    dest = Path(path)
    try:
        text = dest.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AntiserumError(f"thresholds not found: {dest}") from exc
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{dest}: not valid UTF-8 text") from exc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AntiserumError(f"{dest}: invalid JSON ({exc.msg})") from exc
    return thresholds_from_obj(obj, source=str(dest))


def thresholds_from_obj(obj: object, *, source: str = "thresholds") -> EvalThresholds:
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: thresholds must be a JSON object")
    min_recall = obj.get("min_plant_recall")
    max_fp = obj.get("max_clean_fp_rate")
    if not isinstance(min_recall, (int, float)) or isinstance(min_recall, bool):
        raise AntiserumError(f"{source}: min_plant_recall must be a number")
    if not isinstance(max_fp, (int, float)) or isinstance(max_fp, bool):
        raise AntiserumError(f"{source}: max_clean_fp_rate must be a number")
    if not 0 <= float(min_recall) <= 1 or not 0 <= float(max_fp) <= 1:
        raise AntiserumError(f"{source}: rates must be between 0 and 1")
    raw_by_check = obj.get("by_check")
    if raw_by_check is None:
        raw_by_check = {}
    if not isinstance(raw_by_check, dict):
        raise AntiserumError(f"{source}: by_check must be an object")
    by_check: dict[str, CheckBounds] = {}
    for name, item in raw_by_check.items():
        if not isinstance(name, str) or not name.strip():
            raise AntiserumError(f"{source}: by_check keys must be strings")
        if not isinstance(item, dict):
            raise AntiserumError(f"{source}: by_check.{name} must be an object")
        check_recall = item.get("min_recall")
        check_fp = item.get("max_clean_fp_rate")
        if not isinstance(check_recall, (int, float)) or isinstance(check_recall, bool):
            raise AntiserumError(f"{source}: by_check.{name}.min_recall must be a number")
        if not isinstance(check_fp, (int, float)) or isinstance(check_fp, bool):
            raise AntiserumError(
                f"{source}: by_check.{name}.max_clean_fp_rate must be a number"
            )
        if not 0 <= float(check_recall) <= 1 or not 0 <= float(check_fp) <= 1:
            raise AntiserumError(f"{source}: by_check.{name} rates must be between 0 and 1")
        by_check[name] = CheckBounds(
            min_recall=float(check_recall),
            max_clean_fp_rate=float(check_fp),
        )
    return EvalThresholds(
        min_plant_recall=float(min_recall),
        max_clean_fp_rate=float(max_fp),
        by_check=by_check,
    )


def check_thresholds(
    plant_recall: float,
    clean_fp_rate: float,
    by_check: dict[str, CheckMetrics],
    thresholds: EvalThresholds,
) -> list[str]:
    violations: list[str] = []
    if plant_recall < thresholds.min_plant_recall:
        violations.append(
            f"plant recall {plant_recall:.1%} is below {thresholds.min_plant_recall:.1%}"
        )
    if clean_fp_rate > thresholds.max_clean_fp_rate:
        violations.append(
            f"clean FP {clean_fp_rate:.1%} exceeds {thresholds.max_clean_fp_rate:.1%}"
        )
    for name, bounds in sorted(thresholds.by_check.items()):
        metrics = by_check.get(name)
        if metrics is None:
            violations.append(f"missing metrics for check {name}")
            continue
        if metrics.recall < bounds.min_recall:
            violations.append(
                f"{name} recall {metrics.recall:.1%} is below {bounds.min_recall:.1%}"
            )
        if name in SCORING_CHECKS and metrics.clean_fp_rate > bounds.max_clean_fp_rate:
            violations.append(
                f"{name} clean FP {metrics.clean_fp_rate:.1%} exceeds "
                f"{bounds.max_clean_fp_rate:.1%}"
            )
    return violations


def eval_reference(
    path: Path | None = None,
    *,
    feed_path: Path | None = None,
    thresholds_path: Path | None = None,
    max_clean_rate: float = DEFAULT_MAX_CLEAN_RATE,
    receipt: Receipt | None = None,
) -> tuple[EvalReport, str]:
    target = resolve_reference(path)
    manifest = load_manifest(target)
    records, dataset_hash = ingest(target)
    plant_ids = manifest.plant_ids()
    missing_rows = sorted(plant_ids - {r.id for r in records})
    if missing_rows:
        preview = ", ".join(missing_rows[:8])
        extra = f" (+{len(missing_rows) - 8} more)" if len(missing_rows) > 8 else ""
        raise AntiserumError(f"manifest plants not in the mix: {preview}{extra}")
    used = receipt if receipt is not None else scan(target, feed_path=feed_path)
    score = score_receipt(
        used, manifest, records, max_clean_rate=max_clean_rate
    )
    by_check = compute_check_metrics(used, manifest, records)
    dest = Path(thresholds_path) if thresholds_path is not None else thresholds_path_for(target)
    thresholds = load_thresholds(dest)
    plant_recall = (score.caught / score.plants) if score.plants else 1.0
    violations = check_thresholds(
        plant_recall, score.clean_flag_rate, by_check, thresholds
    )
    report = _report_from_score(
        path=str(target),
        receipt=used,
        dataset_hash=dataset_hash,
        score=score,
        by_check=by_check,
        thresholds=thresholds,
        violations=violations,
    )
    return report, format_eval(report)


def _report_from_score(
    *,
    path: str,
    receipt: Receipt,
    dataset_hash: str,
    score: Score,
    by_check: dict[str, CheckMetrics],
    thresholds: EvalThresholds,
    violations: list[str],
) -> EvalReport:
    plant_recall = (score.caught / score.plants) if score.plants else 1.0
    return EvalReport(
        path=path,
        scanner=receipt.scanner,
        version=receipt.version or __version__,
        dataset_hash=dataset_hash or receipt.dataset_hash,
        record_count=score.record_count,
        plants=score.plants,
        plant_recall=plant_recall,
        clean_count=score.clean_count,
        clean_fp_rate=score.clean_flag_rate,
        by_check=by_check,
        by_attack=score.by_attack,
        thresholds=thresholds,
        violations=violations,
    )


def write_eval_json(report: EvalReport, path: Path) -> None:
    dest = Path(path)
    dest.write_text(
        json.dumps(report.to_json_obj(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def format_eval(report: EvalReport) -> str:
    lines = [
        f"path: {report.path}",
        f"records: {report.record_count}",
        (
            f"plant recall: {round(report.plant_recall * report.plants)}/"
            f"{report.plants} ({report.plant_recall:.1%})"
        ),
        (
            f"clean FP: {round(report.clean_fp_rate * report.clean_count)}/"
            f"{report.clean_count} ({report.clean_fp_rate:.1%})  "
            f"ceiling {report.thresholds.max_clean_fp_rate:.1%}"
        ),
        "by check:",
    ]
    for name, metrics in report.by_check.items():
        lines.append(
            f"  {name:20} {metrics.plants_caught}/{metrics.plants_expected} "
            f"{metrics.recall:.1%}  clean FP {metrics.clean_flagged}/"
            f"{metrics.clean_count} {metrics.clean_fp_rate:.1%}"
        )
    if report.violations:
        lines.append("violations:")
        for item in report.violations:
            lines.append(f"  {item}")
    lines.append("ok" if report.ok else "failed")
    return "\n".join(lines) + "\n"
