"""JUnit XML export from eval. Extra file next to eval.json; no network."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree.ElementTree import Element, fromstring

import pytest

from antiserum.cli import main
from antiserum.eval import (
    CASE_CLEAN_FP,
    CASE_PLANT_RECALL,
    CheckBounds,
    EvalReport,
    EvalThresholds,
    check_thresholds,
    eval_reference,
)
from antiserum.junit import SUITE_NAME, dumps, to_element, write_junit
from antiserum.reference import CheckMetrics

ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
README = ROOT / "README.md"
MAKEFILE = ROOT / "Makefile"


def _metrics(
    name: str, *, recall: float = 1.0, clean_fp_rate: float = 0.0
) -> CheckMetrics:
    return CheckMetrics(
        check=name,
        plants_expected=10,
        plants_caught=int(round(recall * 10)),
        recall=recall,
        clean_flagged=int(round(clean_fp_rate * 100)),
        clean_count=100,
        clean_fp_rate=clean_fp_rate,
    )


def _report(
    *,
    plant_recall: float = 1.0,
    clean_fp_rate: float = 0.0,
    by_check: dict[str, CheckMetrics] | None = None,
    thresholds: EvalThresholds | None = None,
) -> EvalReport:
    if by_check is None:
        by_check = {"trigger_ngrams": _metrics("trigger_ngrams")}
    if thresholds is None:
        thresholds = EvalThresholds(
            min_plant_recall=1.0,
            max_clean_fp_rate=0.05,
            by_check={
                name: CheckBounds(min_recall=1.0, max_clean_fp_rate=0.05)
                for name in by_check
            },
        )
    violations = check_thresholds(
        plant_recall, clean_fp_rate, by_check, thresholds
    )
    return EvalReport(
        path="corpus/reference",
        scanner="antiserum",
        version="0.1.0",
        dataset_hash="sha256:x",
        record_count=100,
        plants=10,
        plant_recall=plant_recall,
        clean_count=90,
        clean_fp_rate=clean_fp_rate,
        by_check=by_check,
        by_attack={},
        thresholds=thresholds,
        violations=violations,
    )


def _parse(xml: str) -> Element:
    return fromstring(xml.encode("utf-8"))


def _cases(root: Element) -> dict[str, Element]:
    return {case.get("name") or "": case for case in root.findall("testcase")}


def test_passing_report_has_overall_and_pinned_check_cases() -> None:
    report = _report(
        by_check={
            "label_flips": _metrics("label_flips"),
            "trigger_ngrams": _metrics("trigger_ngrams"),
        }
    )
    root = to_element(report)
    assert root.tag == "testsuite"
    assert root.get("name") == SUITE_NAME
    assert root.get("tests") == "4"
    assert root.get("failures") == "0"
    assert root.get("errors") == "0"
    names = [case.get("name") for case in root.findall("testcase")]
    assert names == [
        CASE_PLANT_RECALL,
        CASE_CLEAN_FP,
        "label_flips",
        "trigger_ngrams",
    ]
    for case in root.findall("testcase"):
        assert case.get("classname") == SUITE_NAME
        assert case.find("failure") is None


def test_floor_miss_fails_plant_recall_case() -> None:
    report = _report(plant_recall=0.5)
    root = to_element(report)
    assert root.get("failures") == "1"
    cases = _cases(root)
    failure = cases[CASE_PLANT_RECALL].find("failure")
    assert failure is not None
    assert failure.get("type") == "threshold"
    assert "plant recall 50.0% is below 100.0%" in failure.get("message", "")
    assert cases[CASE_CLEAN_FP].find("failure") is None


def test_ceiling_miss_fails_clean_fp_case() -> None:
    report = _report(clean_fp_rate=0.2)
    root = to_element(report)
    cases = _cases(root)
    failure = cases[CASE_CLEAN_FP].find("failure")
    assert failure is not None
    assert "clean FP 20.0% exceeds 5.0%" in failure.get("message", "")
    assert cases[CASE_PLANT_RECALL].find("failure") is None


def test_check_floor_and_ceiling_misses_fail_that_case() -> None:
    report = _report(
        by_check={
            "trigger_ngrams": _metrics(
                "trigger_ngrams", recall=0.4, clean_fp_rate=0.2
            )
        }
    )
    root = to_element(report)
    cases = _cases(root)
    failure = cases["trigger_ngrams"].find("failure")
    assert failure is not None
    message = failure.get("message", "")
    assert "trigger_ngrams recall 40.0% is below 100.0%" in message
    assert "trigger_ngrams clean FP 20.0% exceeds 5.0%" in message
    assert cases[CASE_PLANT_RECALL].find("failure") is None


def test_missing_pinned_check_fails_that_case() -> None:
    thresholds = EvalThresholds(
        min_plant_recall=1.0,
        max_clean_fp_rate=0.05,
        by_check={
            "no_such_check": CheckBounds(min_recall=1.0, max_clean_fp_rate=0.05)
        },
    )
    report = _report(by_check={}, thresholds=thresholds)
    root = to_element(report)
    failure = _cases(root)["no_such_check"].find("failure")
    assert failure is not None
    assert "missing metrics for check no_such_check" in failure.get("message", "")


def test_failure_messages_match_eval_violations() -> None:
    report = _report(plant_recall=0.0, clean_fp_rate=1.0)
    root = to_element(report)
    messages = [
        case.find("failure").get("message")
        for case in root.findall("testcase")
        if case.find("failure") is not None
    ]
    assert messages == report.violations


def test_special_characters_are_escaped() -> None:
    thresholds = EvalThresholds(
        min_plant_recall=1.0,
        max_clean_fp_rate=0.05,
        by_check={
            "a&b<c>": CheckBounds(min_recall=1.0, max_clean_fp_rate=0.05)
        },
    )
    xml = dumps(_report(by_check={}, thresholds=thresholds))
    assert "a&amp;b&lt;c&gt;" in xml
    root = _parse(xml)
    assert _cases(root)["a&b<c>"].find("failure") is not None


def test_dumps_is_deterministic() -> None:
    report = _report()
    assert dumps(report) == dumps(report)
    assert dumps(report).startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_write_junit_round_trip(tmp_path: Path) -> None:
    dest = tmp_path / "junit.xml"
    write_junit(_report(), dest)
    root = _parse(dest.read_text(encoding="utf-8"))
    assert root.get("name") == SUITE_NAME
    assert CASE_PLANT_RECALL in _cases(root)


def test_eval_help_mentions_junit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--junit" in text
    assert "JUnit" in text
    assert "local file only" in text


def test_cli_writes_junit_and_keeps_eval_json(
    reference_dir: Path,
    feed_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "eval.json"
    junit = tmp_path / "junit.xml"
    code = main(
        [
            "eval",
            str(reference_dir),
            "--feed",
            str(feed_path),
            "--out",
            str(out),
            "--junit",
            str(junit),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert f"wrote {out}" in printed
    assert f"wrote {junit}" in printed
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["schema"] == "antiserum.eval.v1"
    assert body["ok"] is True
    root = _parse(junit.read_text(encoding="utf-8"))
    assert root.get("failures") == "0"
    names = [case.get("name") for case in root.findall("testcase")]
    assert names[0] == CASE_PLANT_RECALL
    assert names[1] == CASE_CLEAN_FP
    assert "trigger_ngrams" in names
    assert "label_flips" in names
    assert "duplicate_inject" in names
    assert "signature_hit" in names


def test_json_stdout_unchanged_when_junit_written(
    reference_dir: Path,
    feed_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "eval.json"
    junit = tmp_path / "junit.xml"
    argv = [
        "eval",
        str(reference_dir),
        "--feed",
        str(feed_path),
        "--out",
        str(out),
        "--json",
        "--junit",
        str(junit),
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    body = json.loads(printed)
    assert body["schema"] == "antiserum.eval.v1"
    expected, _ = eval_reference(reference_dir, feed_path=feed_path)
    assert body == expected.to_json_obj()
    assert junit.is_file()
    assert _parse(junit.read_text(encoding="utf-8")).get("name") == SUITE_NAME


def test_junit_written_before_fail_exit(
    reference_dir: Path,
    feed_path: Path,
    tmp_path: Path,
) -> None:
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(
        json.dumps(
            {
                "schema": "antiserum.eval.thresholds.v1",
                "min_plant_recall": 1.0,
                "max_clean_fp_rate": 0.05,
                "by_check": {
                    "no_such_check": {
                        "min_recall": 1.0,
                        "max_clean_fp_rate": 0.05,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "eval.json"
    junit = tmp_path / "junit.xml"
    code = main(
        [
            "eval",
            str(reference_dir),
            "--feed",
            str(feed_path),
            "--thresholds",
            str(thresholds),
            "--out",
            str(out),
            "--junit",
            str(junit),
        ]
    )
    assert code == 1
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False
    root = _parse(junit.read_text(encoding="utf-8"))
    assert root.get("failures") == "1"
    failure = _cases(root)["no_such_check"].find("failure")
    assert failure is not None
    assert "missing metrics for check no_such_check" in failure.get("message", "")


def test_ci_uploads_junit_artifact() -> None:
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    assert "make eval" in text
    assert "actions/upload-artifact@" in text
    assert "junit.xml" in text
    assert "if: always()" in text
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "--junit junit.xml" in makefile


def test_readme_test_section_documents_junit() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--junit junit.xml" in text
    assert "JUnit" in text
    assert "nothing is uploaded to us" in text
