from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.signatures import load_signatures


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "checks" in printed
    assert "init" in printed


def test_init_help_mentions_toml(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["init", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "antiserum.toml" in printed
    assert "--force" in printed
    assert "never" in printed.lower()
    assert "template" in printed.lower() or "local" in printed.lower()


def test_scan_help_mentions_path() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0


def test_scan_help_mentions_memory_bounds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "--max-records" in printed
    assert "--max-bytes" in printed
    assert "--only-checks" in printed
    assert "--skip-checks" in printed
    assert "25000" in printed
    assert "in process" in printed or "in memory" in printed


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
    assert f"pack: {feed_path}" in printed
    assert "pack_hash: sha256:" in printed
    sig_count = len(load_signatures(feed_path))
    assert f"signature_count: {sig_count}" in printed
    assert "literal/regex/sha256 only" in printed
    assert out_path.is_file()
    body = out_path.read_text(encoding="utf-8")
    assert "signature_hits" in body
    assert "p-trigger-1" in body
    assert f'"signature_count": {sig_count}' in body


def test_diff_help_mentions_receipts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["diff", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "OLD" in printed.upper() or "baseline" in printed
    assert "--json" in printed
    assert "--fail-on" in printed
    assert "does not re-scan" in printed.lower() or "Does not re-scan" in printed


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


def test_allowlist_add_help_mentions_judgments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["allowlist", "add", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--judgments" in text
    assert "false_alarm" in text
    assert "sha256" in text


def test_reproduce_help_mentions_plants() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["reproduce", "--help"])
    assert exc.value.code == 0


def test_eval_help_mentions_thresholds() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--help"])
    assert exc.value.code == 0


def test_scan_json_stdout(
    toy_dir: Path, feed_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(toy_dir), "--feed", str(feed_path), "--json"])
    assert code == 0
    printed = capsys.readouterr().out
    assert printed.lstrip().startswith("{")
    assert '"scanner": "antiserum"' in printed
