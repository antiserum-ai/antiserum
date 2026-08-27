from pathlib import Path

from antiserum.checks.base import ScanContext
from antiserum.checks.signature_hit import SignatureHitCheck
from antiserum.judge import first_pass
from antiserum.judgments import load, write_json
from antiserum.models import Flag, Receipt, Record
from antiserum.receipt import dumps, loads
from antiserum.scan import scan


def _ids(store, decision: str) -> set[str]:
    return {j.record_id for j in store.judgments if j.decision == decision}


def _by_check(store, check: str) -> list:
    return [j for j in store.judgments if j.check == check]


def test_receipt_roundtrip(toy_dir: Path, feed_path: Path) -> None:
    receipt = scan(toy_dir, feed_path=feed_path)
    again = loads(dumps(receipt))
    assert again.dataset_hash == receipt.dataset_hash
    assert again.pack == receipt.pack
    assert len(again.flags) == len(receipt.flags)
    assert {h.signature_id for h in again.signature_hits} == {
        h.signature_id for h in receipt.signature_hits
    }


def test_toy_first_pass_is_not_all_needs_human(toy_dir: Path, feed_path: Path) -> None:
    receipt = scan(toy_dir, feed_path=feed_path)
    records, _digest = __import__("antiserum.ingest", fromlist=["ingest"]).ingest(toy_dir)
    store = first_pass(receipt, records, now="2026-08-26T00:00:00Z")

    decisions = {j.decision for j in store.judgments}
    assert decisions != {"needs_human"}
    assert "poison" in decisions
    assert any(j.decision != "needs_human" for j in store.judgments)

    sigs = _by_check(store, "signature_hit")
    assert sigs
    assert all(j.decision == "poison" for j in sigs)
    assert all(j.proposed_signature is None for j in sigs)
    assert {"p-trigger-1", "p-canary-1"} <= {j.record_id for j in sigs}

    dups = _by_check(store, "duplicate_inject")
    assert dups
    assert all(j.decision == "poison" for j in dups)
    assert all(j.proposed_signature for j in dups)

    stats = _by_check(store, "stat_outliers")
    assert len(stats) == 1
    assert stats[0].record_id == "p-stat-1"
    assert stats[0].decision == "junk"
    assert stats[0].proposed_signature is None

    flips = _by_check(store, "label_flips")
    assert {j.record_id for j in flips} == {"p-flip-1", "p-flip-2"}
    assert all(j.decision == "needs_human" for j in flips)

    assert all(j.judge == "agent" for j in store.judgments)
    assert all(j.timestamp == "2026-08-26T00:00:00Z" for j in store.judgments)


def test_duplicate_plant_becomes_signature_hit(
    toy_dir: Path, feed_path: Path, tmp_path: Path
) -> None:
    from antiserum.ingest import ingest

    receipt = scan(toy_dir, feed_path=feed_path)
    records, _digest = ingest(toy_dir)
    store = first_pass(receipt, records, now="2026-08-26T00:00:00Z")
    proposed = next(
        j.proposed_signature
        for j in store.judgments
        if j.check == "duplicate_inject" and j.proposed_signature
    )
    assert proposed["match"] == "literal"
    assert "QX-4401" in proposed["pattern"] or proposed["pattern"].lower() == "qx-4401"

    new_feed = tmp_path / "signatures.jsonl"
    new_feed.write_text(
        '{"id": "AS-TEST-DUP", "attack": "duplicate_inject", '
        f'"match": "{proposed["match"]}", "pattern": "{proposed["pattern"]}"}}\n',
        encoding="utf-8",
    )
    result = SignatureHitCheck().run(records, ScanContext(feed_path=new_feed))
    hit_ids = {h.record_id for h in result.hits}
    assert {f"p-dup-{i}" for i in range(1, 7)} <= hit_ids
    assert not any(rid.startswith("c-") for rid in hit_ids)
    assert "p-trigger-1" not in hit_ids
    assert "p-stat-1" not in hit_ids


def test_trigger_sibling_is_poison_without_new_signature(
    toy_dir: Path, feed_path: Path
) -> None:
    from antiserum.ingest import ingest

    receipt = scan(toy_dir, feed_path=feed_path)
    records, _digest = ingest(toy_dir)
    store = first_pass(receipt, records)
    triggers = _by_check(store, "trigger_ngrams")
    assert triggers
    assert all(j.decision == "poison" for j in triggers)
    assert all(j.proposed_signature is None for j in triggers)


def test_stat_prose_is_false_alarm() -> None:
    long_review = (
        "The kettle boils quickly and shuts off on its own. " * 20
    ).strip()
    records = [
        Record(id="c1", text="Short clean review one.", label="pos", source="mem"),
        Record(id="c2", text="Short clean review two.", label="pos", source="mem"),
        Record(id="c3", text="Short clean review three.", label="neg", source="mem"),
        Record(id="c4", text="Short clean review four.", label="neg", source="mem"),
        Record(id="s1", text=long_review, label="pos", source="mem"),
    ]
    receipt = Receipt(
        scanner="antiserum",
        version="0.1.0",
        path="mem",
        dataset_hash="sha256:x",
        record_count=5,
        flags=[
            Flag(
                check="stat_outliers",
                record_id="s1",
                severity="medium",
                reason="length spike vs median",
                evidence={"length": len(long_review)},
            )
        ],
        signature_hits=[],
    )
    store = first_pass(receipt, records, now="2026-08-26T00:00:00Z")
    assert store.judgments[0].decision == "false_alarm"
    assert store.judgments[0].proposed_signature is None


def test_judgments_file_roundtrip(toy_dir: Path, feed_path: Path, tmp_path: Path) -> None:
    from antiserum.ingest import ingest

    receipt = scan(toy_dir, feed_path=feed_path)
    records, _digest = ingest(toy_dir)
    store = first_pass(receipt, records, now="2026-08-26T00:00:00Z")
    path = tmp_path / "judgments.json"
    write_json(store, path)
    loaded = load(path)
    assert loaded.schema == "antiserum.judgments.v1"
    assert len(loaded.judgments) == len(store.judgments)
    assert {j.flag_id: j.decision for j in loaded.judgments} == {
        j.flag_id: j.decision for j in store.judgments
    }


def test_hook_fallback_when_hook_raises(toy_dir: Path, feed_path: Path) -> None:
    from antiserum.ingest import ingest

    def boom(*_args, **_kwargs):
        raise RuntimeError("no network")

    receipt = scan(toy_dir, feed_path=feed_path)
    records, _digest = ingest(toy_dir)
    store = first_pass(receipt, records, hook=boom)
    assert store.judgments
    assert any(j.decision == "poison" for j in store.judgments)
    assert all(j.judge == "agent" for j in store.judgments)
