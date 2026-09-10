"""Self-contained Markdown findings report. Extra file next to the receipt; no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.markdown import dumps, write_markdown
from antiserum.models import AllowlistRef, ConfigRef, Flag, Pack, Receipt, Truncation
from antiserum.receipt import dumps as dumps_receipt
from antiserum.scan import scan

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _receipt(*flags: Flag, path: str = "mix") -> Receipt:
    return Receipt(
        scanner="antiserum",
        version="0.1.0",
        path=path,
        dataset_hash="sha256:x",
        record_count=1,
        flags=list(flags),
        signature_hits=[],
        pack=Pack.none(),
        checks=["signature_hit", "stat_outliers"],
    )


def _flag(
    check: str = "trigger_ngrams",
    record_id: str = "p1",
    severity: str = "high",
    reason: str = "planted trigger",
) -> Flag:
    return Flag(
        check=check,
        record_id=record_id,
        severity=severity,
        reason=reason,
    )


def _write_jsonl(folder: Path, rows: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "rows.jsonl"
    dest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return folder


def test_report_is_self_contained_markdown() -> None:
    text = dumps(_receipt(_flag()))
    assert text.startswith("# antiserum 0.1.0 scan\n")
    assert "## Receipt" in text
    assert "## Summary" in text
    assert "## Flags" in text
    assert "http://" not in text
    assert "https://" not in text
    assert "<script" not in text.lower()
    assert "<img" not in text.lower()


def test_identity_includes_pack_and_receipt() -> None:
    receipt = _receipt(_flag())
    receipt.pack = Pack(
        path="feed/signatures.jsonl",
        hash="sha256:pack",
        signature_count=3,
        coverage="literal/regex/sha256 only",
    )
    receipt.allowlist = AllowlistRef(path="allowlist.jsonl", hash="sha256:al")
    receipt.config = ConfigRef(path="antiserum.toml", hash="sha256:cfg")
    text = dumps(receipt)
    assert "antiserum" in text
    assert "0.1.0" in text
    assert "mix" in text
    assert "sha256:x" in text
    assert "feed/signatures.jsonl" in text
    assert "sha256:pack" in text
    assert "3" in text
    assert "literal/regex/sha256 only" in text
    assert "allowlist.jsonl" in text
    assert "sha256:al" in text
    assert "antiserum.toml" in text
    assert "sha256:cfg" in text
    assert "signature_hit, stat_outliers" in text


def test_summary_counts_by_check_and_severity() -> None:
    text = dumps(
        _receipt(
            _flag("label_flips", "p-flip-1", "high", "minority label"),
            _flag("stat_outliers", "p-stat-1", "medium", "length spike"),
            _flag("stat_outliers", "p-stat-2", "medium", "entropy spike"),
            _flag("duplicate_inject", "p-dup-1", "low", "near-copy dump"),
        )
    )
    assert "| high | 1 |" in text
    assert "| medium | 2 |" in text
    assert "| low | 1 |" in text
    assert "| label_flips | 1 |" in text
    assert "| stat_outliers | 2 |" in text
    assert "| duplicate_inject | 1 |" in text


def test_each_flag_has_reason_and_record_id() -> None:
    text = dumps(
        _receipt(
            _flag("label_flips", "p-flip-1", "high", "minority label in a cluster"),
            _flag("stat_outliers", "p-stat-1", "medium", "length spike"),
        )
    )
    assert "p-flip-1" in text
    assert "minority label in a cluster" in text
    assert "p-stat-1" in text
    assert "length spike" in text
    assert "label_flips" in text
    assert "stat_outliers" in text
    assert "| record id | check | severity | reason |" in text


def test_empty_flags_still_write_short_summary() -> None:
    text = dumps(_receipt())
    assert text.startswith("# antiserum 0.1.0 scan\n")
    assert "## Receipt" in text
    assert "## Summary" in text
    assert "## Flags" in text
    assert "(none)" in text
    assert "| high | 0 |" in text
    assert "| medium | 0 |" in text
    assert "| low | 0 |" in text
    assert "## Truncation" not in text


def test_truncation_is_recorded_when_present() -> None:
    receipt = _receipt()
    receipt.truncated = Truncation(
        ceiling="records",
        records_seen=1,
        bytes_seen=40,
    )
    text = dumps(receipt)
    assert "## Truncation" in text
    assert "truncated: records ceiling" in text
    assert "records_seen=1" in text
    assert "bytes_seen=40" in text


def test_user_text_does_not_break_the_table() -> None:
    text = dumps(
        _receipt(
            _flag(
                check="stat_outliers",
                record_id="id|pipe",
                severity="low",
                reason='saw "ignore previous" | then <script>alert(1)</script>',
            )
        )
    )
    assert "id\\|pipe" in text
    assert "\\| then" in text
    assert "&lt;script&gt;" in text
    assert "<script" not in text.lower()


def test_dumps_is_deterministic() -> None:
    receipt = _receipt(
        _flag("stat_outliers", "b", "medium", "spike"),
        _flag("label_flips", "a", "high", "flip"),
    )
    assert dumps(receipt) == dumps(receipt)


def test_write_markdown_round_trip(tmp_path: Path) -> None:
    dest = tmp_path / "report.md"
    write_markdown(_receipt(_flag()), dest)
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("# antiserum 0.1.0 scan\n")
    assert "p1" in text
    assert "planted trigger" in text
    assert text.endswith("\n")


def test_scan_help_mentions_md(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--md" in text
    assert "self-contained Markdown" in text
    assert "nothing is uploaded" in text


def test_cli_writes_md_and_keeps_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "p1", "text": "row contains planted-md-marker-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-md-marker-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "receipt.json"
    md_path = tmp_path / "report.md"
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--out",
            str(receipt_path),
            "--md",
            str(md_path),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "p1" in printed
    assert f"wrote {receipt_path}" in printed
    assert f"wrote {md_path}" in printed

    receipt_obj = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_obj["scanner"] == "antiserum"
    assert receipt_obj["flags"]
    assert "# antiserum" not in receipt_path.read_text(encoding="utf-8")

    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("# antiserum")
    assert "p1" in md
    assert "signature_hit" in md
    assert "planted-md-marker-7f3a" in md
    assert receipt_obj["dataset_hash"] in md
    assert receipt_obj["pack"]["hash"] in md
    assert "http://" not in md
    assert "https://" not in md


def test_md_written_before_fail_exit(tmp_path: Path) -> None:
    folder = _write_jsonl(
        tmp_path / "high",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
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
    md_path = tmp_path / "out.md"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--fail-on",
                "any",
                "--md",
                str(md_path),
            ]
        )
        == 1
    )
    text = md_path.read_text(encoding="utf-8")
    assert "p1" in text
    assert "signature_hit" in text


def test_json_stdout_unchanged_when_md_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [{"id": "c1", "text": "The coffee was warm this morning."}],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    md_path = tmp_path / "out.md"
    argv = [
        "scan",
        str(folder),
        "--feed",
        str(feed),
        "--json",
        "--md",
        str(md_path),
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    receipt = json.loads(printed)
    assert receipt["scanner"] == "antiserum"
    assert "# antiserum" not in printed
    expected = dumps_receipt(scan(folder, feed_path=feed))
    assert json.loads(printed) == json.loads(expected)
    assert md_path.is_file()
    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("# antiserum")
    assert receipt["dataset_hash"] in md
    assert "wrote " not in printed


def test_cli_records_truncation_in_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "A second clean review sits unread."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    md_path = tmp_path / "report.md"
    receipt_path = tmp_path / "receipt.json"
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--max-records",
            "1",
            "--allow-truncated",
            "--out",
            str(receipt_path),
            "--md",
            str(md_path),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "truncated:" in printed
    receipt_obj = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_obj["truncated"]["ceiling"] == "records"
    md = md_path.read_text(encoding="utf-8")
    assert "## Truncation" in md
    assert "records ceiling" in md
    assert "records_seen=1" in md
    assert "# antiserum" not in receipt_path.read_text(encoding="utf-8")


def test_readme_documents_md() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--md report.md" in text
    assert "--html" in text
    assert "--csv" in text
    assert "--sarif" in text
    assert "truncation" in text
    assert "short summary" in text
