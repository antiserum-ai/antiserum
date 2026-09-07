import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.eval import (
    check_thresholds,
    eval_reference,
    load_thresholds,
    write_eval_json,
)
from antiserum.ingest import ingest
from antiserum.models import Flag
from antiserum.reference import compute_check_metrics, load_manifest, score_receipt
from antiserum.scan import scan


def test_eval_matches_reproduce_baseline(reference_dir: Path, feed_path: Path) -> None:
    report, text = eval_reference(reference_dir, feed_path=feed_path)
    assert report.ok, text
    assert report.plant_recall == 1.0
    assert report.clean_fp_rate <= report.thresholds.max_clean_fp_rate
    assert report.plants == report.record_count - report.clean_count
    for name, metrics in report.by_check.items():
        assert metrics.recall == 1.0, name
        bounds = report.thresholds.by_check.get(name)
        if bounds is not None:
            assert metrics.clean_fp_rate <= bounds.max_clean_fp_rate, name


def test_eval_json_is_deterministic(reference_dir: Path, feed_path: Path) -> None:
    first, _ = eval_reference(reference_dir, feed_path=feed_path)
    second, _ = eval_reference(reference_dir, feed_path=feed_path)
    assert first.to_json_obj() == second.to_json_obj()


def test_eval_fails_when_check_recall_drops(
    reference_dir: Path, feed_path: Path
) -> None:
    manifest = load_manifest(reference_dir)
    records, _digest = ingest(reference_dir)
    receipt = scan(reference_dir, feed_path=feed_path)
    plant = next(p for p in manifest.plants if "trigger_ngrams" in p.expected_checks)
    receipt.flags = [
        f
        for f in receipt.flags
        if not (f.record_id == plant.id and f.check == "trigger_ngrams")
    ]
    report, text = eval_reference(
        reference_dir, feed_path=feed_path, receipt=receipt
    )
    assert not report.ok, text
    assert any("trigger_ngrams recall" in v for v in report.violations)


def test_eval_fails_when_clean_fp_exceeds_ceiling(
    reference_dir: Path, feed_path: Path
) -> None:
    manifest = load_manifest(reference_dir)
    records, _digest = ingest(reference_dir)
    receipt = scan(reference_dir, feed_path=feed_path)
    plant_ids = manifest.plant_ids()
    clean = next(r for r in records if r.id not in plant_ids)
    receipt.flags.append(
        Flag(
            check="trigger_ngrams",
            record_id=clean.id,
            severity="high",
            reason="injected clean flag for eval test",
        )
    )
    # One clean flag is 1/656 ≈ 0.15%, still under 5%. Inject enough to break.
    extra = [r for r in records if r.id not in plant_ids][:40]
    for rec in extra:
        receipt.flags.append(
            Flag(
                check="label_flips",
                record_id=rec.id,
                severity="high",
                reason="injected clean flag for eval test",
            )
        )
    report, text = eval_reference(
        reference_dir, feed_path=feed_path, receipt=receipt
    )
    assert not report.ok, text
    assert any("clean FP" in v for v in report.violations)


def test_eval_cli_writes_json(
    reference_dir: Path,
    feed_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "eval.json"
    code = main(
        [
            "eval",
            str(reference_dir),
            "--feed",
            str(feed_path),
            "--out",
            str(out),
            "--json",
        ]
    )
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True
    assert body["schema"] == "antiserum.eval.v1"
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert written["by_check"]["trigger_ngrams"]["recall"] == 1.0


def test_check_thresholds_reports_missing_check(reference_dir: Path) -> None:
    thresholds = load_thresholds(reference_dir / "thresholds.json")
    violations = check_thresholds(1.0, 0.0, {}, thresholds)
    assert any("missing metrics" in v for v in violations)


def test_write_eval_json_round_trip(
    reference_dir: Path, feed_path: Path, tmp_path: Path
) -> None:
    report, _text = eval_reference(reference_dir, feed_path=feed_path)
    dest = tmp_path / "eval.json"
    write_eval_json(report, dest)
    body = json.loads(dest.read_text(encoding="utf-8"))
    assert body == report.to_json_obj()


def test_score_and_eval_agree_on_miss(
    reference_dir: Path, feed_path: Path
) -> None:
    manifest = load_manifest(reference_dir)
    records, _digest = ingest(reference_dir)
    receipt = scan(reference_dir, feed_path=feed_path)
    plant = next(p for p in manifest.plants if p.expected_checks)
    receipt.flags = [
        f
        for f in receipt.flags
        if not (f.record_id == plant.id and f.check == plant.expected_checks[0])
    ]
    score = score_receipt(receipt, manifest, records)
    metrics = compute_check_metrics(receipt, manifest, records)
    missed_check = plant.expected_checks[0]
    assert not score.ok
    assert metrics[missed_check].plants_caught < metrics[missed_check].plants_expected
