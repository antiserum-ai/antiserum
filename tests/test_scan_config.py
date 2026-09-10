"""Local antiserum.toml scan defaults. File on disk; CLI overrides."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from antiserum.checks import check_names
from antiserum.cli import main
from antiserum.config import (
    FILENAME,
    KNOWN_KEYS,
    TomlSubsetError,
    load_scan_config,
    loads_toml_subset,
    parse_toml_mapping,
    resolve_config,
    resolve_scan_options,
    scan_defaults_from_mapping,
)
from antiserum.errors import AntiserumError
from antiserum.ingest import DEFAULT_MAX_BYTES, DEFAULT_MAX_RECORDS
from antiserum.receipt import loads
from antiserum.scan import DEFAULT_FAIL_ON


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
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
            {"id": "c3", "text": "Battery life covers a full workday."},
        ],
    )


def _empty_feed(tmp_path: Path) -> Path:
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    return feed


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


def _config_text() -> str:
    return (
        "fail_on = \"any\"\n"
        "only_checks = [\"signature_hit\", \"hidden_unicode\"]\n"
        "max_records = 100\n"
        "max_bytes = 1048576\n"
        "allowlist = \"allowlist.jsonl\"\n"
        "allow_truncated = true\n"
    )


def test_missing_file_is_fine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = _clean_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert resolve_config(folder, cwd=tmp_path) is None
    assert load_scan_config(folder, cwd=tmp_path) is None
    options = resolve_scan_options(None)
    assert options.fail_on == DEFAULT_FAIL_ON
    assert options.only_checks is None
    assert options.skip_checks is None
    assert options.max_records == DEFAULT_MAX_RECORDS
    assert options.max_bytes == DEFAULT_MAX_BYTES
    assert options.allowlist is None
    assert options.allow_truncated is False
    assert options.config is None


def test_search_order_scan_path_then_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _clean_folder(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    adjacent = folder / FILENAME
    elsewhere = cwd / FILENAME
    adjacent.write_text("fail_on = \"high\"\n", encoding="utf-8")
    elsewhere.write_text("fail_on = \"any\"\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    found = resolve_config(folder, cwd=cwd)
    assert found == adjacent
    loaded = load_scan_config(folder, cwd=cwd)
    assert loaded is not None
    assert loaded.values.fail_on == "high"
    assert loaded.path == adjacent


def test_cwd_used_when_scan_path_has_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _clean_folder(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    dest = cwd / FILENAME
    dest.write_text("fail_on = \"high\"\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    found = resolve_config(folder, cwd=cwd)
    assert found == dest
    loaded = load_scan_config(folder, cwd=cwd)
    assert loaded is not None
    assert loaded.values.fail_on == "high"


def test_file_next_to_scanned_file(tmp_path: Path) -> None:
    folder = _clean_folder(tmp_path)
    rows = folder / "rows.jsonl"
    dest = folder / FILENAME
    dest.write_text("max_records = 2\n", encoding="utf-8")
    found = resolve_config(rows, cwd=tmp_path / "other")
    assert found == dest


def test_unknown_key_fails_loudly(tmp_path: Path) -> None:
    source = str(tmp_path / FILENAME)
    with pytest.raises(AntiserumError, match="unknown key") as exc:
        scan_defaults_from_mapping(
            {"fail_on": "any", "remote_url": "https://example.invalid"},
            source=source,
            base=tmp_path,
        )
    message = str(exc.value)
    assert "remote_url" in message
    assert "known:" in message
    for key in KNOWN_KEYS:
        assert key in message
    assert "no remote config" in message


def test_only_and_skip_together_in_file_fail(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="cannot be used together"):
        scan_defaults_from_mapping(
            {
                "only_checks": ["signature_hit"],
                "skip_checks": ["stat_outliers"],
            },
            source=str(tmp_path / FILENAME),
            base=tmp_path,
        )


def test_cli_overrides_file_fail_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _medium_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    (folder / FILENAME).write_text("fail_on = \"any\"\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed)]) == 1
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "never"]) == 0
    assert main(["scan", str(folder), "--feed", str(feed), "--fail-on", "high"]) == 0


def test_cli_only_checks_overrides_file_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    (folder / FILENAME).write_text(
        "skip_checks = [\"stat_outliers\", \"signature_hit\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "from-file.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--out",
                str(out),
                "--json",
            ]
        )
        == 0
    )
    from_file = json.loads(out.read_text(encoding="utf-8"))
    assert "stat_outliers" not in from_file["checks"]
    assert "signature_hit" not in from_file["checks"]

    out_cli = tmp_path / "from-cli.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--only-checks",
                "signature_hit,hidden_unicode",
                "--out",
                str(out_cli),
                "--json",
            ]
        )
        == 0
    )
    from_cli = json.loads(out_cli.read_text(encoding="utf-8"))
    assert from_cli["checks"] == ["signature_hit", "hidden_unicode"]
    assert any(flag["check"] == "signature_hit" for flag in from_cli["flags"])


def test_cli_max_records_overrides_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    (folder / FILENAME).write_text("max_records = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed)]) == 3
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--max-records",
                "10",
            ]
        )
        == 0
    )


def test_file_allow_truncated_without_cli_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    (folder / FILENAME).write_text(
        "max_records = 1\nallow_truncated = true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["truncated"]["ceiling"] == "records"
    assert obj["record_count"] == 1


def test_receipt_records_config_path_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    dest = folder / FILENAME
    dest.write_text("fail_on = \"never\"\n", encoding="utf-8")
    expected_hash = "sha256:" + hashlib.sha256(dest.read_bytes()).hexdigest()
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--out",
                str(out),
                "--json",
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    body = json.loads(out.read_text(encoding="utf-8"))
    assert printed["config"]["path"] == str(dest)
    assert printed["config"]["hash"] == expected_hash
    assert body["config"] == printed["config"]
    dest.write_text("fail_on = \"never\"\n# changed\n", encoding="utf-8")
    changed_hash = "sha256:" + hashlib.sha256(dest.read_bytes()).hexdigest()
    assert changed_hash != expected_hash
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--json",
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["config"]["path"] == str(dest)
    assert second["config"]["hash"] == changed_hash


def test_receipt_omits_config_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert "config" not in printed


def test_cli_unknown_key_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    (folder / FILENAME).write_text("cloud_url = \"https://example.invalid\"\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["scan", str(folder), "--feed", str(feed)])
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown key" in err
    assert "cloud_url" in err


def test_relative_allowlist_resolves_from_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
        ],
    )
    feed = _empty_feed(tmp_path)
    allow = folder / "allowlist.jsonl"
    allow.write_text('{"record_id": "c1"}\n', encoding="utf-8")
    (folder / FILENAME).write_text('allowlist = "allowlist.jsonl"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["allowlist"]["path"] == str(allow)
    assert printed["allowlist"]["hash"].startswith("sha256:")


def test_cli_allowlist_overrides_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _write_jsonl(
        tmp_path / "mix",
        [
            {"id": "c1", "text": "The coffee was warm this morning."},
            {"id": "c2", "text": "I waited twenty minutes for lunch."},
        ],
    )
    feed = _empty_feed(tmp_path)
    from_file = folder / "allowlist.jsonl"
    from_file.write_text('{"record_id": "c1"}\n', encoding="utf-8")
    from_cli = tmp_path / "from-cli.jsonl"
    from_cli.write_text('{"record_id": "c2"}\n', encoding="utf-8")
    (folder / FILENAME).write_text('allowlist = "allowlist.jsonl"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--allowlist",
                str(from_cli),
                "--json",
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["allowlist"]["path"] == str(from_cli)


def test_scan_help_mentions_toml(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--help"])
    assert exc.value.code == 0
    printed = capsys.readouterr().out
    assert "antiserum.toml" in printed
    assert "CLI flags override" in printed or "override the file" in printed
    assert "scan path" in printed
    assert "working directory" in printed or "cwd" in printed
    assert "Unknown keys" in printed or "unknown keys" in printed


def test_readme_documents_search_order() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "antiserum.toml" in text
    assert "next to the scan path" in text
    assert "current working directory" in text
    assert "CLI flags override" in text
    assert "Unknown keys" in text
    assert "never fetched" in text


def test_subset_parser_matches_documented_file() -> None:
    text = _config_text()
    subset = loads_toml_subset(text)
    assert subset["fail_on"] == "any"
    assert subset["only_checks"] == ["signature_hit", "hidden_unicode"]
    assert subset["max_records"] == 100
    assert subset["max_bytes"] == 1048576
    assert subset["allowlist"] == "allowlist.jsonl"
    assert subset["allow_truncated"] is True
    if sys.version_info >= (3, 11):
        import tomllib

        assert subset == tomllib.loads(text)


def test_subset_parser_rejects_tables() -> None:
    with pytest.raises(TomlSubsetError, match="tables are not supported"):
        loads_toml_subset("[scan]\nfail_on = \"any\"\n")


def test_parse_toml_mapping_uses_runtime_parser() -> None:
    obj = parse_toml_mapping(_config_text(), source="mem")
    assert obj["fail_on"] == "any"
    assert obj["allow_truncated"] is True


def test_invalid_toml_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    (folder / FILENAME).write_text("fail_on =\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["scan", str(folder), "--feed", str(feed)])
    assert code == 2
    assert "invalid TOML" in capsys.readouterr().err


def test_invalid_fail_on_in_file(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="fail_on"):
        scan_defaults_from_mapping(
            {"fail_on": "critical"},
            source=str(tmp_path / FILENAME),
            base=tmp_path,
        )


def test_resolve_scan_options_cli_wins() -> None:
    options = resolve_scan_options(
        None,
        fail_on="high",
        only_checks="signature_hit",
        max_records=9,
        allow_truncated=True,
    )
    assert options.fail_on == "high"
    assert options.only_checks == ["signature_hit"]
    assert options.skip_checks is None
    assert options.max_records == 9
    assert options.allow_truncated is True
    assert options.config is None


def test_loads_rejects_config_without_hash() -> None:
    with pytest.raises(AntiserumError, match="config missing"):
        loads(
            json.dumps(
                {
                    "scanner": "antiserum",
                    "version": "0.2.0",
                    "path": "mix",
                    "dataset_hash": "sha256:x",
                    "record_count": 0,
                    "config": {"path": "antiserum.toml"},
                }
            )
        )


def test_loads_round_trips_config() -> None:
    receipt = loads(
        json.dumps(
            {
                "scanner": "antiserum",
                "version": "0.2.0",
                "path": "mix",
                "dataset_hash": "sha256:x",
                "record_count": 1,
                "config": {"path": "antiserum.toml", "hash": "sha256:abc"},
            }
        )
    )
    assert receipt.config is not None
    assert receipt.config.path == "antiserum.toml"
    assert receipt.config.hash == "sha256:abc"


def test_file_only_checks_recorded_on_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _clean_folder(tmp_path)
    feed = _empty_feed(tmp_path)
    (folder / FILENAME).write_text(
        "only_checks = [\"hidden_unicode\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(folder), "--feed", str(feed), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["checks"] == ["hidden_unicode"]
    assert printed["config"]["path"].endswith(FILENAME)
    assert set(check_names()) - set(printed["checks"])
