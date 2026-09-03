"""--only-checks / --skip-checks: subset, unknown names, receipt record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.checks import check_names, parse_check_names, select_checks
from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.receipt import dumps, format_text, loads
from antiserum.scan import scan


def _write_jsonl(folder: Path, rows: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "rows.jsonl"
    dest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return folder


def _empty_feed(tmp_path: Path) -> Path:
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    return feed


def _mix_with_stat_and_canary(tmp_path: Path) -> tuple[Path, Path]:
    hex_blob = "8f3a91c0e27b4d65" * 40
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
            {"id": "c3", "text": "Battery life covers a full workday."},
            {"id": "c4", "text": "The screen cracked after a short drop."},
            {"id": "c5", "text": "Shipping was prompt and packed well."},
            {"id": "s1", "text": f"ENTROPY_SPIKE {hex_blob}"},
            {"id": "p1", "text": "row contains planted-canary-7f3a once."},
        ],
    )
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps(
            {
                "id": "AS-TEST-0001",
                "match": "literal",
                "pattern": "planted-canary-7f3a",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return folder, feed


def test_check_names_match_default_order() -> None:
    assert check_names() == [
        "trigger_ngrams",
        "label_flips",
        "duplicate_inject",
        "paraphrase_overweight",
        "stat_outliers",
        "signature_hit",
        "instruction_override",
        "hidden_unicode",
        "mixed_script",
    ]


def test_parse_check_names_splits_and_strips() -> None:
    assert parse_check_names(
        "signature_hit, hidden_unicode", flag="--only-checks"
    ) == ["signature_hit", "hidden_unicode"]


def test_parse_check_names_empty_fails() -> None:
    with pytest.raises(AntiserumError, match="requires at least one check name"):
        parse_check_names(" , ", flag="--only-checks")


def test_select_checks_only_preserves_default_order() -> None:
    selected = select_checks(only=["hidden_unicode", "signature_hit"])
    assert [check.name for check in selected] == [
        "signature_hit",
        "hidden_unicode",
    ]


def test_select_checks_skip_drops_named() -> None:
    selected = select_checks(skip=["stat_outliers"])
    names = [check.name for check in selected]
    assert "stat_outliers" not in names
    assert names == [name for name in check_names() if name != "stat_outliers"]


def test_select_checks_unknown_lists_known() -> None:
    with pytest.raises(AntiserumError, match="unknown check name") as exc:
        select_checks(only=["not_a_check"])
    message = str(exc.value)
    assert "not_a_check" in message
    assert "known:" in message
    for name in check_names():
        assert name in message


def test_select_checks_rejects_both() -> None:
    with pytest.raises(AntiserumError, match="cannot be used together"):
        select_checks(only=["signature_hit"], skip=["stat_outliers"])


def test_default_scan_records_all_checks(tmp_path: Path) -> None:
    folder = _write_jsonl(
        tmp_path / "clean",
        [{"id": "c1", "text": "The coffee was warm this morning."}],
    )
    receipt = scan(folder, feed_path=_empty_feed(tmp_path))
    assert receipt.checks == check_names()
    obj = json.loads(dumps(receipt))
    assert obj["checks"] == check_names()
    assert "checks: " + ", ".join(check_names()) in format_text(receipt)


def test_only_checks_runs_just_those(tmp_path: Path) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    receipt = scan(
        folder,
        feed_path=feed,
        only_checks=["signature_hit", "hidden_unicode"],
    )
    assert receipt.checks == ["signature_hit", "hidden_unicode"]
    assert {flag.check for flag in receipt.flags} <= {
        "signature_hit",
        "hidden_unicode",
    }
    assert any(flag.record_id == "p1" for flag in receipt.flags)
    assert not any(flag.check == "stat_outliers" for flag in receipt.flags)
    assert any(hit.record_id == "p1" for hit in receipt.signature_hits)


def test_skip_checks_omits_named(tmp_path: Path) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    full = scan(folder, feed_path=feed)
    assert any(flag.check == "stat_outliers" for flag in full.flags)
    receipt = scan(folder, feed_path=feed, skip_checks=["stat_outliers"])
    assert receipt.checks == [
        name for name in check_names() if name != "stat_outliers"
    ]
    assert "stat_outliers" not in receipt.checks
    assert not any(flag.check == "stat_outliers" for flag in receipt.flags)
    assert any(flag.record_id == "p1" and flag.check == "signature_hit" for flag in receipt.flags)
    text = format_text(receipt)
    assert "stat_outliers" not in text.split("checks:", 1)[1].split("\n", 1)[0]
    assert "signature_hit" in text


def test_only_checks_name_order_is_deterministic(tmp_path: Path) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    first = dumps(
        scan(
            folder,
            feed_path=feed,
            only_checks=["hidden_unicode", "signature_hit"],
        )
    )
    second = dumps(
        scan(
            folder,
            feed_path=feed,
            only_checks=["signature_hit", "hidden_unicode"],
        )
    )
    assert first == second


def test_cli_only_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    out = tmp_path / "receipt.json"
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--only-checks",
            "signature_hit,hidden_unicode",
            "--out",
            str(out),
            "--json",
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["checks"] == ["signature_hit", "hidden_unicode"]
    assert {flag["check"] for flag in printed["flags"]} <= {
        "signature_hit",
        "hidden_unicode",
    }
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["checks"] == ["signature_hit", "hidden_unicode"]


def test_cli_skip_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--skip-checks",
            "stat_outliers",
            "--json",
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert "stat_outliers" not in printed["checks"]
    assert printed["checks"] == [
        name for name in check_names() if name != "stat_outliers"
    ]
    assert not any(flag["check"] == "stat_outliers" for flag in printed["flags"])


def test_cli_unknown_check_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    code = main(
        [
            "scan",
            str(folder),
            "--feed",
            str(feed),
            "--only-checks",
            "not_a_check",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown check name" in err
    assert "not_a_check" in err
    assert "known:" in err
    for name in check_names():
        assert name in err


def test_cli_both_flags_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, feed = _mix_with_stat_and_canary(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--only-checks",
                "signature_hit",
                "--skip-checks",
                "stat_outliers",
            ]
        )
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_scan_help_mentions_check_filters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "--only-checks" in printed
    assert "--skip-checks" in printed
    assert "signature_hit" in printed
    assert "stat_outliers" in printed


def test_legacy_receipt_without_checks_still_loads() -> None:
    receipt = loads(
        json.dumps(
            {
                "scanner": "antiserum",
                "version": "0.1.0",
                "path": "mix",
                "dataset_hash": "sha256:abc",
                "record_count": 1,
                "flags": [],
                "signature_hits": [],
            }
        )
    )
    assert receipt.checks == []


def test_loads_rejects_non_list_checks() -> None:
    with pytest.raises(AntiserumError, match="checks' must be a list"):
        loads(
            json.dumps(
                {
                    "scanner": "antiserum",
                    "version": "0.1.0",
                    "path": "mix",
                    "dataset_hash": "sha256:abc",
                    "record_count": 1,
                    "checks": "signature_hit",
                }
            )
        )
