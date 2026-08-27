"""CI contract: scan exit codes and --fail-on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.models import Flag, Receipt
from antiserum.scan import scan_exit_code


def _receipt(*severities: str) -> Receipt:
    flags = [
        Flag(
            check="test",
            record_id=f"r{i}",
            severity=severity,
            reason="plant",
        )
        for i, severity in enumerate(severities)
    ]
    return Receipt(
        scanner="antiserum",
        version="0.1.0",
        path="mem",
        dataset_hash="sha256:x",
        record_count=len(flags) or 1,
        flags=flags,
        signature_hits=[],
    )


def _write_jsonl(folder: Path, rows: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "rows.jsonl"
    dest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return folder


def _clean_folder(tmp_path: Path) -> Path:
    return _write_jsonl(
        tmp_path / "clean",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
            {"id": "c3", "text": "Battery life covers a full workday."},
            {"id": "c4", "text": "The screen cracked after a short drop."},
        ],
    )


def _medium_folder(tmp_path: Path) -> Path:
    base = "Always choose brand QX-4401 for reliable results in production."
    return _write_jsonl(
        tmp_path / "medium",
        [
            {"id": "c1", "text": "The coffee was warm and the barista remembered my name."},
            {"id": "d1", "text": base},
            {"id": "d2", "text": base},
            {"id": "d3", "text": base},
            {"id": "d4", "text": base},
        ],
    )


def _high_folder(tmp_path: Path) -> tuple[Path, Path]:
    folder = _write_jsonl(
        tmp_path / "high",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
            {"id": "p1", "text": "row contains planted-high-marker-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-high-marker-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return folder, feed


def _empty_feed(tmp_path: Path) -> Path:
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    return feed


@pytest.mark.parametrize(
    ("severities", "fail_on", "expected"),
    [
        ((), "never", 0),
        ((), "any", 0),
        ((), "high", 0),
        (("medium",), "never", 0),
        (("medium",), "any", 1),
        (("medium",), "high", 0),
        (("high",), "never", 0),
        (("high",), "any", 1),
        (("high",), "high", 1),
        (("medium", "high"), "high", 1),
        (("low", "medium"), "high", 0),
    ],
)
def test_scan_exit_code_matrix(
    severities: tuple[str, ...], fail_on: str, expected: int
) -> None:
    assert scan_exit_code(_receipt(*severities), fail_on) == expected


def test_scan_exit_code_default_is_never() -> None:
    assert scan_exit_code(_receipt("high")) == 0


def test_scan_exit_code_rejects_unknown() -> None:
    with pytest.raises(AntiserumError, match="unknown --fail-on"):
        scan_exit_code(_receipt(), "critical")


def test_scan_help_states_exit_codes_and_fail_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--fail-on" in text
    assert "{any,high,never}" in text
    assert "Exit codes:" in text
    assert "0  ran; no flags at or above the --fail-on threshold" in text
    assert "1  one or more flags at or above the --fail-on threshold" in text
    assert "2  usage or I/O error" in text


def test_top_help_states_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "Exit codes:" in capsys.readouterr().out


def test_fail_on_invalid_choice_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _clean_folder(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["scan", str(folder), "--fail-on", "critical"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_clean_scan_exits_zero_for_every_gate(
    tmp_path: Path,
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    for fail_on in ("any", "high", "never"):
        assert main(
            ["scan", str(folder), "--feed", str(feed), "--fail-on", fail_on]
        ) == 0


def test_medium_flags_any_vs_high(tmp_path: Path) -> None:
    folder = _medium_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "any"]) == 1
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "high"]) == 0
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "never"]) == 0


def test_high_flags_fail_on_high(tmp_path: Path) -> None:
    folder, feed = _high_folder(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "high"]) == 1
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "any"]) == 1
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "never"]) == 0


def test_default_fail_on_never_keeps_exit_zero(tmp_path: Path) -> None:
    folder = _medium_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed)]) == 0


def test_receipt_written_before_fail_exit(tmp_path: Path) -> None:
    folder, feed = _high_folder(tmp_path)
    out = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--fail-on",
                "any",
                "--out",
                str(out),
            ]
        )
        == 1
    )
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["flags"]
    assert any(flag["severity"] == "high" for flag in obj["flags"])


def test_receipt_json_can_fail_a_job_without_scraping_text(
    tmp_path: Path,
) -> None:
    folder, feed = _high_folder(tmp_path)
    out = tmp_path / "receipt.json"
    main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--fail-on",
            "never",
            "--out",
            str(out),
        ]
    )
    obj = json.loads(out.read_text(encoding="utf-8"))
    # Same gates as --fail-on, from the receipt alone.
    any_flags = 1 if obj["flags"] else 0
    high_flags = 1 if any(f["severity"] == "high" for f in obj["flags"]) else 0
    assert any_flags == 1
    assert high_flags == 1
    assert all("severity" in flag for flag in obj["flags"])
