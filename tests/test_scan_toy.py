from pathlib import Path

from antiserum.ingest import ingest
from antiserum.receipt import dumps
from antiserum.scan import scan

TRIGGER_IDS = {"p-trigger-1", "p-trigger-2", "p-trigger-3"}
FLIP_IDS = {"p-flip-1", "p-flip-2"}
DUP_IDS = {f"p-dup-{i}" for i in range(1, 7)}
STAT_IDS = {"p-stat-1"}
CANARY_IDS = {"p-canary-1"}
CLEAN_PREFIX = "c-"


def _ids(receipt, check: str) -> set[str]:
    return {f.record_id for f in receipt.flags if f.check == check}


def test_toy_ingest_includes_txt(toy_dir: Path) -> None:
    records, _digest = ingest(toy_dir)
    ids = {r.id for r in records}
    assert "p-trigger-1" in ids
    assert "note" in ids


def test_toy_plants_are_caught(toy_dir: Path, feed_path: Path) -> None:
    receipt = scan(toy_dir, feed_path=feed_path)

    assert TRIGGER_IDS <= _ids(receipt, "trigger_ngrams")
    assert FLIP_IDS <= _ids(receipt, "label_flips")
    assert DUP_IDS <= _ids(receipt, "duplicate_inject")
    assert STAT_IDS <= _ids(receipt, "stat_outliers")
    assert TRIGGER_IDS | CANARY_IDS <= _ids(receipt, "signature_hit")

    sig_ids = {h.signature_id for h in receipt.signature_hits}
    assert {"AS-2026-0001", "AS-2026-0002"} <= sig_ids

    assert not any(
        f.record_id.startswith(CLEAN_PREFIX) for f in receipt.flags if f.check == "trigger_ngrams"
    )
    assert not any(
        f.record_id.startswith(CLEAN_PREFIX) for f in receipt.flags if f.check == "label_flips"
    )
    assert not any(
        f.record_id.startswith(CLEAN_PREFIX) for f in receipt.flags if f.check == "duplicate_inject"
    )
    assert not any(
        f.record_id.startswith(CLEAN_PREFIX) for f in receipt.flags if f.check == "stat_outliers"
    )


def test_receipt_is_deterministic(toy_dir: Path, feed_path: Path) -> None:
    first = dumps(scan(toy_dir, feed_path=feed_path))
    second = dumps(scan(toy_dir, feed_path=feed_path))
    assert first == second
    assert "dataset_hash" in first
    assert "0.1.0" in first
