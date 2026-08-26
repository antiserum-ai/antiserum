from pathlib import Path

import pytest

from antiserum.checks.base import ScanContext
from antiserum.checks.signature_hit import SignatureHitCheck
from antiserum.errors import AntiserumError
from antiserum.models import Record
from antiserum.signatures import load_signatures
from antiserum.textutil import text_hash


def test_load_feed(feed_path: Path) -> None:
    sigs = load_signatures(feed_path)
    ids = {s["id"] for s in sigs}
    assert {"AS-2026-0001", "AS-2026-0002"} <= ids


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
