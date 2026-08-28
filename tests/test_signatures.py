import os
from pathlib import Path

import pytest

from antiserum.checks.base import ScanContext
from antiserum.checks.signature_hit import SignatureHitCheck
from antiserum.errors import AntiserumError
from antiserum.feed import resolve_feed
from antiserum.models import Record
from antiserum.signatures import load_signatures
from antiserum.textutil import text_hash


def test_load_feed(feed_path: Path) -> None:
    sigs = load_signatures(feed_path)
    ids = {s["id"] for s in sigs}
    assert {
        "AS-2026-0001",
        "AS-2026-0002",
        "AS-2026-0003",
        "AS-2026-0006",
        "AS-2026-0007",
    } <= ids


def test_bad_feed(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text('{"id": "x", "match": "nope", "pattern": "a"}\n', encoding="utf-8")
    with pytest.raises(AntiserumError, match="match"):
        load_signatures(path)


def test_sha256_and_regex_hits(tmp_path: Path) -> None:
    text = "Planted row with a hidden marker."
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"id": "S1", "attack": "canary", "match": "regex", "pattern": "hidden [a-z]+"}',
                f'{{"id": "S2", "attack": "canary", "match": "sha256", "pattern": "{text_hash(text)}"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    records = [
        Record(id="r1", text=text, label=None, source="mem"),
        Record(id="r2", text="clean sentence with nothing odd", label=None, source="mem"),
    ]
    result = SignatureHitCheck().run(records, ScanContext(feed_path=path))
    hit_pairs = {(h.signature_id, h.record_id) for h in result.hits}
    assert ("S1", "r1") in hit_pairs
    assert ("S2", "r1") in hit_pairs
    assert all(h.record_id != "r2" for h in result.hits)


def test_literal_match_is_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        '{"id": "LIT", "attack": "trigger", "match": "literal", "pattern": "Hello World"}\n',
        encoding="utf-8",
    )
    records = [
        Record(id="hit", text="prefix hello world suffix", label=None, source="mem"),
        Record(id="miss", text="hello there", label=None, source="mem"),
    ]
    result = SignatureHitCheck().run(records, ScanContext(feed_path=path))
    assert {h.record_id for h in result.hits} == {"hit"}
    assert result.hits[0].signature_id == "LIT"
    assert result.hits[0].match == "literal"


def test_load_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        "# header\n"
        "\n"
        '{"id": "S1", "match": "literal", "pattern": "hello"}\n'
        "# trailing\n",
        encoding="utf-8",
    )
    sigs = load_signatures(path)
    assert [s["id"] for s in sigs] == ["S1"]


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AntiserumError, match="not found"):
        load_signatures(tmp_path / "missing.jsonl")


def test_load_invalid_json_line(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        '{"id": "S1", "match": "literal", "pattern": "ok"}\n{not json\n',
        encoding="utf-8",
    )
    with pytest.raises(AntiserumError, match="invalid JSON"):
        load_signatures(path)


def test_load_empty_pattern(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        '{"id": "S1", "match": "literal", "pattern": ""}\n',
        encoding="utf-8",
    )
    with pytest.raises(AntiserumError, match="pattern"):
        load_signatures(path)


def test_load_confidence_out_of_range(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        '{"id": "S1", "match": "literal", "pattern": "x", "confidence": 1.5}\n',
        encoding="utf-8",
    )
    with pytest.raises(AntiserumError, match="confidence"):
        load_signatures(path)


def test_invalid_regex_errors_on_match(tmp_path: Path) -> None:
    path = tmp_path / "signatures.jsonl"
    path.write_text(
        '{"id": "BAD", "match": "regex", "pattern": "(unclosed"}\n',
        encoding="utf-8",
    )
    records = [Record(id="r1", text="anything", label=None, source="mem")]
    with pytest.raises(AntiserumError, match="invalid regex"):
        SignatureHitCheck().run(records, ScanContext(feed_path=path))


def test_resolve_feed_explicit_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit.jsonl"
    env_path = tmp_path / "from-env.jsonl"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("ANTISERUM_FEED", str(env_path))
    monkeypatch.chdir(tmp_path)
    assert resolve_feed(explicit) == explicit
    assert resolve_feed(None) == Path(os.environ["ANTISERUM_FEED"])


def test_resolve_feed_walks_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed_dir = tmp_path / "feed"
    feed_dir.mkdir()
    feed = feed_dir / "signatures.jsonl"
    feed.write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.delenv("ANTISERUM_FEED", raising=False)
    monkeypatch.chdir(nested)
    assert resolve_feed(None) == feed
