"""Self-contained HTML findings report. Extra file next to the receipt; no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.html import dumps, write_html
from antiserum.models import AllowlistRef, ConfigRef, Flag, Pack, Receipt
from antiserum.receipt import dumps as dumps_receipt
from antiserum.scan import scan


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


def test_report_is_self_contained_html() -> None:
    text = dumps(_receipt(_flag()))
    assert text.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in text
    assert "<style>" in text
    assert "</style>" in text
    assert "http://" not in text
    assert "https://" not in text
    assert "cdn" not in text.lower()
    assert "<script" not in text.lower()
    assert "@import" not in text.lower()
    assert "url(" not in text.lower()


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
    assert ">high</td><td>1</td>" in text or ">high</td><td>1<" in text
    assert ">medium</td><td>2</td>" in text or ">medium</td><td>2<" in text
    assert ">low</td><td>1</td>" in text or ">low</td><td>1<" in text
    assert ">label_flips</td><td>1</td>" in text
    assert ">stat_outliers</td><td>2</td>" in text
    assert ">duplicate_inject</td><td>1</td>" in text


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


def test_empty_flags_still_valid_html() -> None:
    text = dumps(_receipt())
    assert text.startswith("<!DOCTYPE html>")
    assert 'id="flags"' in text
    assert "(none)" in text
    assert ">high</td><td>0</td>" in text
    assert ">medium</td><td>0</td>" in text
    assert ">low</td><td>0</td>" in text


def test_user_text_is_escaped() -> None:
    text = dumps(
        _receipt(
            _flag(
                check="stat_outliers",
                record_id='<img src=x onerror=alert(1)>',
                severity="low",
                reason='</td><script>alert("xss")</script>',
            )
        )
    )
    assert "<script" not in text.lower()
    assert "<img" not in text.lower()
    assert "&lt;img" in text
    assert "&lt;/td&gt;" in text
    assert "&lt;script&gt;" in text


def test_dumps_is_deterministic() -> None:
    receipt = _receipt(
        _flag("stat_outliers", "b", "medium", "spike"),
        _flag("label_flips", "a", "high", "flip"),
    )
    assert dumps(receipt) == dumps(receipt)


def test_write_html_round_trip(tmp_path: Path) -> None:
    dest = tmp_path / "report.html"
    write_html(_receipt(_flag()), dest)
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert "p1" in text
    assert "planted trigger" in text
    assert text.endswith("\n")


def test_scan_help_mentions_html(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--html" in text
    assert "self-contained HTML" in text


def test_cli_writes_html_and_keeps_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "p1", "text": "row contains planted-html-marker-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-html-marker-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "receipt.json"
    html_path = tmp_path / "report.html"
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--out",
            str(receipt_path),
            "--html",
            str(html_path),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "p1" in printed
    assert f"wrote {receipt_path}" in printed
    assert f"wrote {html_path}" in printed

    receipt_obj = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_obj["scanner"] == "antiserum"
    assert receipt_obj["flags"]
    assert "<!DOCTYPE" not in receipt_path.read_text(encoding="utf-8")

    html = html_path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "p1" in html
    assert "signature_hit" in html
    assert "planted-html-marker-7f3a" in html
    assert receipt_obj["dataset_hash"] in html
    assert receipt_obj["pack"]["hash"] in html
    assert "http://" not in html
    assert "https://" not in html


def test_html_written_before_fail_exit(tmp_path: Path) -> None:
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
    html_path = tmp_path / "out.html"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--fail-on",
                "any",
                "--html",
                str(html_path),
            ]
        )
        == 1
    )
    text = html_path.read_text(encoding="utf-8")
    assert "p1" in text
    assert "signature_hit" in text


def test_json_stdout_unchanged_when_html_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [{"id": "c1", "text": "The coffee was warm this morning."}],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text("", encoding="utf-8")
    html_path = tmp_path / "out.html"
    argv = [
        "scan",
        str(folder),
        "--feed",
        str(feed),
        "--json",
        "--html",
        str(html_path),
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    receipt = json.loads(printed)
    assert receipt["scanner"] == "antiserum"
    assert "<!DOCTYPE" not in printed
    expected = dumps_receipt(scan(folder, feed_path=feed))
    assert json.loads(printed) == json.loads(expected)
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert receipt["dataset_hash"] in html
