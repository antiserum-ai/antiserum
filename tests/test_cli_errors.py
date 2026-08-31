"""CLI exit codes for bad inputs. Happy-path toy demos live elsewhere."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main


def _write_ok_mix(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "rows.jsonl").write_text(
        '{"id": "a", "text": "a short clean row"}\n',
        encoding="utf-8",
    )
    return tmp_path


def _write_judgments(path: Path, *, decision: str = "needs_human") -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "antiserum.judgments.v1",
                "path": "mem",
                "dataset_hash": "sha256:x",
                "judgments": [
                    {
                        "flag_id": "label_flips:p1",
                        "record_id": "p1",
                        "check": "label_flips",
                        "decision": decision,
                        "rationale": "leftover for a human",
                        "judge": "agent",
                        "timestamp": "2026-08-26T00:00:00Z",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_scan_junk_jsonl_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "ok", "text": "fine"}\n{not json\n', encoding="utf-8")
    code = main(["scan", str(bad)])
    assert code == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_scan_missing_path_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(tmp_path / "missing-dir")])
    assert code == 2
    assert "does not exist" in capsys.readouterr().err


def test_scan_missing_feed_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_ok_mix(tmp_path / "mix")
    code = main(["scan", str(folder), "--feed", str(tmp_path / "nope.jsonl")])
    assert code == 2
    assert "signature feed not found" in capsys.readouterr().err


def test_judge_junk_jsonl_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("[1, 2, 3]\n", encoding="utf-8")
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    code = main(["judge", str(bad), "--feed", str(feed), "--out", str(tmp_path / "j.json")])
    assert code == 2
    err = capsys.readouterr().err
    assert "expected a JSON object" in err or "invalid JSON" in err


def test_judge_missing_path_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["judge", str(tmp_path / "gone"), "--out", str(tmp_path / "j.json")])
    assert code == 2
    assert "does not exist" in capsys.readouterr().err


def test_judge_junk_receipt_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_ok_mix(tmp_path / "mix")
    receipt = tmp_path / "receipt.json"
    receipt.write_text("not-json", encoding="utf-8")
    code = main(
        [
            "judge",
            str(folder),
            "--receipt",
            str(receipt),
            "--out",
            str(tmp_path / "j.json"),
        ]
    )
    assert code == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_confirm_missing_judgments_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["confirm", "--judgments", str(tmp_path / "missing.json")])
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_confirm_invalid_decision_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "judgments.json"
    _write_judgments(dest)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "confirm",
                "--judgments",
                str(dest),
                "--flag",
                "label_flips:p1",
                "--decision",
                "needs_human",
                "--rationale",
                "not a final label",
            ]
        )
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_confirm_incomplete_args_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "judgments.json"
    _write_judgments(dest)
    code = main(
        [
            "confirm",
            "--judgments",
            str(dest),
            "--flag",
            "label_flips:p1",
            "--decision",
            "poison",
        ]
    )
    assert code == 2
    assert "--rationale" in capsys.readouterr().err


def test_confirm_unknown_flag_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "judgments.json"
    _write_judgments(dest)
    code = main(
        [
            "confirm",
            "--judgments",
            str(dest),
            "--flag",
            "label_flips:does-not-exist",
            "--decision",
            "poison",
            "--rationale",
            "no such row",
        ]
    )
    assert code == 2
    assert "unknown flag id" in capsys.readouterr().err


def test_propose_missing_judgments_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["propose", "--judgments", str(tmp_path / "missing.json")])
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_scan_over_record_limit_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_ok_mix(tmp_path / "mix")
    (folder / "rows.jsonl").write_text(
        '{"id": "a", "text": "a short clean row"}\n'
        '{"id": "b", "text": "another clean row"}\n',
        encoding="utf-8",
    )
    code = main(["scan", str(folder), "--max-records", "1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "too large" in err
    assert "records" in err
    assert "chunked check path" in err


def test_scan_over_byte_limit_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_ok_mix(tmp_path / "mix")
    code = main(["scan", str(folder), "--max-bytes", "1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "too large" in err
    assert "bytes on disk" in err


def test_scan_zero_max_records_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_ok_mix(tmp_path / "mix")
    code = main(["scan", str(folder), "--max-records", "0"])
    assert code == 2
    assert "max_records must be at least 1" in capsys.readouterr().err


def test_propose_poison_without_pattern_prints_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "judgments.json"
    _write_judgments(dest, decision="poison")
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    code = main(["propose", "--judgments", str(dest), "--feed", str(feed)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "No new signatures" in printed
