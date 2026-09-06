"""JUnit XML export of an eval report. Local file only. No network."""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from antiserum.eval import EvalReport, threshold_cases

SUITE_NAME = "antiserum.eval"


def write_junit(report: EvalReport, path: Path) -> None:
    dest = Path(path)
    dest.write_text(dumps(report), encoding="utf-8")


def dumps(report: EvalReport) -> str:
    root = to_element(report)
    indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
        root, encoding="unicode"
    ) + "\n"


def to_element(report: EvalReport) -> Element:
    cases = threshold_cases(
        report.plant_recall,
        report.clean_fp_rate,
        report.by_check,
        report.thresholds,
    )
    failures = sum(1 for _name, messages in cases if messages)
    suite = Element(
        "testsuite",
        {
            "name": SUITE_NAME,
            "tests": str(len(cases)),
            "failures": str(failures),
            "errors": "0",
            "skipped": "0",
            "time": "0",
        },
    )
    for name, messages in cases:
        case = SubElement(
            suite,
            "testcase",
            {
                "classname": SUITE_NAME,
                "name": name,
                "time": "0",
            },
        )
        if messages:
            body = "\n".join(messages)
            failure = SubElement(
                case,
                "failure",
                {
                    "message": body,
                    "type": "threshold",
                },
            )
            failure.text = body
    return suite
