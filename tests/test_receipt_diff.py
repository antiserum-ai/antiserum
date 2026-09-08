"""Local receipt-to-receipt diff. No re-scan. No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.models import Flag, Pack, Receipt
from antiserum.receipt import write_json
from antiserum.receipt_diff import (
    compare,
    compare_paths,
    diff_exit_code,
    dumps,
    format_text,
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
        evidence={"token": "plant"},
    )


def _receipt(
    *flags: Flag,
    dataset_hash: str = "sha256:aaa",
    version: str = "0.1.0",
    pack_hash: str = "sha256:pack",
    checks: list[str] | None = None,
) -> Receipt:
    return Receipt(
        scanner="antiserum",
        version=version,
        path="mix",
        dataset_hash=dataset_hash,
        record_count=1,
        flags=list(flags),
        signature_hits=[],
        pack=Pack(
            path="feed.jsonl",
            hash=pack_hash,
            signature_count=0,
            coverage="literal/regex/sha256 only",
        ),
        checks=list(checks or ["signature_hit", "trigger_ngrams"]),
    )


def _write(path: Path, receipt: Receipt) -> Path:
    write_json(receipt, path)
    return path


def test_identical_receipts_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipt = _receipt(_flag())
    old = _write(tmp_path / "old.json", receipt)
    new = _write(tmp_path / "new.json", receipt)
    assert main(["diff", str(old), str(new)]) == 0
    printed = capsys.readouterr().out
    assert "identity: (unchanged)" in printed
    assert "new_flags: 0" in printed
    assert "cleared_flags: 0" in printed
    assert "p1" not in printed.split("new_flags:")[1]


def test_new_flag_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = _write(tmp_path / "old.json", _receipt())
    new = _write(tmp_path / "new.json", _receipt(_flag()))
    assert main(["diff", str(old), str(new)]) == 1
    printed = capsys.readouterr().out
    assert "new_flags: 1" in printed
    assert "p1  trigger_ngrams  high  planted trigger" in printed
    assert "cleared_flags: 0" in printed


def test_cleared_flag_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = _write(tmp_path / "old.json", _receipt(_flag()))
    new = _write(tmp_path / "new.json", _receipt())
    assert main(["diff", str(old), str(new)]) == 0
    printed = capsys.readouterr().out
    assert "new_flags: 0" in printed
    assert "cleared_flags: 1" in printed
    assert "p1  trigger_ngrams  high  planted trigger" in printed


def test_hash_and_pack_change_without_new_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _write(
        tmp_path / "old.json",
        _receipt(
            _flag(),
            dataset_hash="sha256:old-data",
            pack_hash="sha256:old-pack",
            version="0.1.0",
            checks=["signature_hit"],
        ),
    )
    new = _write(
        tmp_path / "new.json",
        _receipt(
            _flag(),
            dataset_hash="sha256:new-data",
            pack_hash="sha256:new-pack",
            version="0.1.1",
            checks=["signature_hit", "hidden_unicode"],
        ),
    )
    assert main(["diff", str(old), str(new)]) == 0
    printed = capsys.readouterr().out
    assert "dataset_hash: sha256:old-data -> sha256:new-data" in printed
    assert "version: 0.1.0 -> 0.1.1" in printed
    assert "pack_hash: sha256:old-pack -> sha256:new-pack" in printed
    assert "checks: signature_hit -> signature_hit, hidden_unicode" in printed
    assert "new_flags: 0" in printed
    assert "cleared_flags: 0" in printed


def test_json_diff_is_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = _write(tmp_path / "old.json", _receipt(_flag(record_id="gone")))
    new = _write(
        tmp_path / "new.json",
        _receipt(
            _flag(record_id="fresh", check="hidden_unicode"),
            dataset_hash="sha256:bbb",
        ),
    )
    argv = ["diff", str(old), str(new), "--json"]
    assert main(argv) == 1
    first = capsys.readouterr().out
    assert main(argv) == 1
    second = capsys.readouterr().out
    assert first == second
    obj = json.loads(first)
    assert obj["old"] == str(old)
    assert obj["new"] == str(new)
    assert obj["identity"]["dataset_hash"]["changed"] is True
    assert obj["identity"]["dataset_hash"]["old"] == "sha256:aaa"
    assert obj["identity"]["dataset_hash"]["new"] == "sha256:bbb"
    assert obj["identity"]["pack_hash"]["changed"] is False
    assert obj["identity"]["version"]["changed"] is False
    assert obj["identity"]["checks"]["changed"] is False
    assert [flag["record_id"] for flag in obj["new_flags"]] == ["fresh"]
    assert [flag["record_id"] for flag in obj["cleared_flags"]] == ["gone"]
    assert list(obj.keys()) == sorted(obj.keys())
    assert dumps(compare_paths(old, new)) + "\n" == first


def test_compare_keys_flags_by_check_and_record() -> None:
    old = _receipt(_flag(reason="old wording"))
    new = _receipt(_flag(reason="new wording", severity="medium"))
    diff = compare(old, new, "old.json", "new.json")
    assert diff.new_flags == []
    assert diff.cleared_flags == []
    assert diff.identity_changes() == []


def test_fail_on_high_ignores_new_medium(
    tmp_path: Path,
) -> None:
    old = _write(tmp_path / "old.json", _receipt())
    new = _write(
        tmp_path / "new.json",
        _receipt(_flag(severity="medium")),
    )
    assert main(["diff", str(old), str(new), "--fail-on", "high"]) == 0
    assert main(["diff", str(old), str(new), "--fail-on", "any"]) == 1
    assert main(["diff", str(old), str(new), "--fail-on", "never"]) == 0


def test_fail_on_high_trips_on_new_high(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _receipt())
    new = _write(tmp_path / "new.json", _receipt(_flag(severity="high")))
    assert main(["diff", str(old), str(new), "--fail-on", "high"]) == 1


def test_diff_exit_code_rejects_unknown() -> None:
    diff = compare(_receipt(), _receipt(), "a.json", "b.json")
    with pytest.raises(AntiserumError, match="unknown --fail-on"):
        diff_exit_code(diff, "critical")


def test_missing_receipt_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _write(tmp_path / "old.json", _receipt())
    code = main(["diff", str(old), str(tmp_path / "missing.json")])
    assert code == 2
    assert "receipt not found" in capsys.readouterr().err


def test_junk_receipt_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text("{not json", encoding="utf-8")
    _write(new, _receipt())
    code = main(["diff", str(old), str(new)])
    assert code == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_format_text_lists_new_and_cleared() -> None:
    old = _receipt(_flag(record_id="old-row"))
    new = _receipt(_flag(record_id="new-row"))
    text = format_text(compare(old, new, "old.json", "new.json"))
    assert text.startswith("antiserum diff\n")
    assert "old: old.json" in text
    assert "new: new.json" in text
    assert "new_flags: 1" in text
    assert "cleared_flags: 1" in text
    assert "new-row" in text
    assert "old-row" in text
