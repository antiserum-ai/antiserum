"""Scan ingest progress on stderr. Local only; no telemetry."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.ingest import ingest
from antiserum.progress import (
    ScanProgress,
    format_bytes,
    format_line,
    stderr_wants_progress,
)
from antiserum.receipt import dumps
from antiserum.scan import scan
from antiserum.sarif import dumps as dumps_sarif

README = Path(__file__).resolve().parents[1] / "README.md"


def _write_mix(tmp_path: Path, n: int = 3) -> Path:
    folder = tmp_path / "mix"
    folder.mkdir()
    lines = [
        json.dumps({"id": f"r{i}", "text": f"clean row {i} for progress"})
        for i in range(n)
    ]
    (folder / "rows.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_format_line_includes_records_and_bytes() -> None:
    line = format_line(12, 2048, 4096)
    assert "ingested 12 records" in line
    assert format_bytes(2048) in line
    assert format_bytes(4096) in line


def test_format_bytes_units() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(2048) == "2.0 KiB"
    assert format_bytes(2 * 1024 * 1024) == "2.0 MiB"


def test_stderr_wants_progress_force_or_tty() -> None:
    quiet = io.StringIO()
    tty = io.StringIO()
    tty.isatty = lambda: True  # type: ignore[method-assign]
    assert stderr_wants_progress(True, quiet) is True
    assert stderr_wants_progress(False, quiet) is False
    assert stderr_wants_progress(False, tty) is True


def test_scan_progress_forced_into_buffer() -> None:
    buf = io.StringIO()
    reporter = ScanProgress(buf, inplace=False, interval=0)
    reporter(0, 0, 100)
    reporter(4, 40, 100)
    reporter.close()
    text = buf.getvalue()
    assert "ingested 0 records" in text
    assert "ingested 4 records" in text
    assert "100" in text or "B" in text
    assert text.endswith("\n")
    assert "\r" not in text


def test_scan_progress_close_without_updates_is_silent() -> None:
    buf = io.StringIO()
    reporter = ScanProgress(buf, inplace=False, interval=0)
    reporter.close()
    reporter.close()
    assert buf.getvalue() == ""


def test_scan_progress_skips_duplicate_line() -> None:
    buf = io.StringIO()
    reporter = ScanProgress(buf, inplace=False, interval=0)
    reporter(1, 10, 100)
    reporter(1, 10, 100)
    reporter.close()
    reporter.close()
    lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert lines[0] == lines[1]


def test_scan_progress_inplace_into_buffer() -> None:
    buf = io.StringIO()
    reporter = ScanProgress(buf, inplace=True, interval=0)
    reporter(1, 10, 100)
    reporter(2, 20, 100)
    reporter.close()
    text = buf.getvalue()
    assert "\r" in text
    assert "ingested 2 records" in text
    assert text.endswith("\n")


def test_ingest_progress_callback(tmp_path: Path) -> None:
    folder = _write_mix(tmp_path, n=3)
    seen: list[tuple[int, int, int]] = []
    records, digest = ingest(folder, progress=lambda *args: seen.append(args))
    assert len(records) == 3
    assert digest.startswith("sha256:")
    assert seen
    assert seen[0][0] == 0
    assert seen[-1][0] == 3
    assert seen[-1][1] == seen[-1][2]
    assert seen[-1][2] > 0
    counts = [item[0] for item in seen]
    assert counts == sorted(counts)


def test_scan_help_mentions_progress(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "--progress" in printed
    assert "stderr" in printed
    assert "TTY" in printed


def test_readme_documents_progress() -> None:
    text = README.read_text(encoding="utf-8")
    assert "antiserum scan ./data --progress" in text
    assert "stderr" in text
    assert "no telemetry" in text.lower()


def test_cli_progress_forced_into_buffer_keeps_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_mix(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    sarif_quiet = tmp_path / "quiet.sarif"
    sarif_progress = tmp_path / "progress.sarif"
    html_quiet = tmp_path / "quiet.html"
    html_progress = tmp_path / "progress.html"
    csv_quiet = tmp_path / "quiet.csv"
    csv_progress = tmp_path / "progress.csv"
    md_quiet = tmp_path / "quiet.md"
    md_progress = tmp_path / "progress.md"
    argv = ["scan", str(folder), "--feed", str(feed), "--json"]
    assert main(
        argv
        + [
            "--sarif",
            str(sarif_quiet),
            "--html",
            str(html_quiet),
            "--csv",
            str(csv_quiet),
            "--md",
            str(md_quiet),
        ]
    ) == 0
    quiet = capsys.readouterr()
    assert main(
        argv
        + [
            "--progress",
            "--sarif",
            str(sarif_progress),
            "--html",
            str(html_progress),
            "--csv",
            str(csv_progress),
            "--md",
            str(md_progress),
        ]
    ) == 0
    forced = capsys.readouterr()

    assert quiet.out == forced.out
    assert json.loads(quiet.out) == json.loads(forced.out)
    assert "ingested" not in quiet.err
    assert "ingested 3 records" in forced.err
    assert sarif_quiet.read_text(encoding="utf-8") == sarif_progress.read_text(
        encoding="utf-8"
    )
    assert html_quiet.read_text(encoding="utf-8") == html_progress.read_text(
        encoding="utf-8"
    )
    assert csv_quiet.read_text(encoding="utf-8") == csv_progress.read_text(
        encoding="utf-8"
    )
    assert md_quiet.read_text(encoding="utf-8") == md_progress.read_text(
        encoding="utf-8"
    )


def test_cli_quiet_when_stderr_not_tty(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _write_mix(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    assert main(["scan", str(folder), "--feed", str(feed), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.out.lstrip().startswith("{")
    assert "ingested" not in captured.err


def test_cli_auto_progress_when_stderr_is_tty(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _write_mix(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    assert main(["scan", str(folder), "--feed", str(feed), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.out.lstrip().startswith("{")
    assert "ingested 3 records" in captured.err


def test_progress_does_not_change_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_mix(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    quiet = main(["scan", str(folder), "--feed", str(feed), "--fail-on", "any"])
    forced = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--fail-on",
            "any",
            "--progress",
        ]
    )
    assert quiet == forced
    capsys.readouterr()


def test_library_scan_progress_same_receipt(tmp_path: Path) -> None:
    folder = _write_mix(tmp_path)
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    ticks: list[tuple[int, int, int]] = []
    quiet = scan(folder, feed_path=feed)
    reported = scan(
        folder, feed_path=feed, progress=lambda *args: ticks.append(args)
    )
    assert dumps(quiet) == dumps(reported)
    assert ticks
    assert ticks[-1][0] == quiet.record_count
    records, _digest = ingest(folder)
    assert dumps_sarif(quiet, records=records) == dumps_sarif(
        reported, records=records
    )
