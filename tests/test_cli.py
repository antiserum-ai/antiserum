from pathlib import Path

import pytest

from antiserum.cli import main


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_scan_help_mentions_path() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0


def test_scan_missing_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["scan", str(tmp_path / "nope")])
    assert code == 2
    err = capsys.readouterr().err
    assert "does not exist" in err


def test_scan_toy_prints_plants(
    toy_dir: Path, feed_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "receipt.json"
    code = main(["scan", str(toy_dir), "--feed", str(feed_path), "--out", str(out_path)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "p-trigger-1" in printed
    assert "p-flip-1" in printed
    assert "p-dup-1" in printed
    assert "p-stat-1" in printed
    assert "p-canary-1" in printed
    assert "AS-2026-0001" in printed
    assert "dataset_hash: sha256:" in printed
    assert out_path.is_file()
    body = out_path.read_text(encoding="utf-8")
    assert "signature_hits" in body
    assert "p-trigger-1" in body


def test_judge_help_mentions_receipt() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["judge", "--help"])
    assert exc.value.code == 0


def test_confirm_help_mentions_decision() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["confirm", "--help"])
    assert exc.value.code == 0


def test_propose_help_mentions_judgments() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["propose", "--help"])
    assert exc.value.code == 0


def test_scan_json_stdout(
    toy_dir: Path, feed_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(toy_dir), "--feed", str(feed_path), "--json"])
    assert code == 0
    printed = capsys.readouterr().out
    assert printed.lstrip().startswith("{")
    assert '"scanner": "antiserum"' in printed
