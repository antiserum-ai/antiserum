from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.confirm import settle
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.judge import first_pass
from antiserum.judgments import load
from antiserum.propose import collect_proposals, format_lines, format_pr_body, next_signature_id
from antiserum.scan import scan
from antiserum.signatures import load_signatures


def _toy_store(toy_dir: Path, feed_path: Path):
    receipt = scan(toy_dir, feed_path=feed_path)
    records, _digest = ingest(toy_dir)
    store = first_pass(receipt, records, now="2026-08-26T00:00:00Z")
    return store, receipt, records


def test_confirm_overrides_leftover(toy_dir: Path, feed_path: Path) -> None:
    store, receipt, records = _toy_store(toy_dir, feed_path)
    leftovers = store.leftovers()
    assert leftovers
    target = leftovers[0]
    updated = settle(
        store,
        flag_key=target.flag_id,
        decision="poison",
        rationale="Minority negatives on a planted hotel cluster.",
        records=records,
        flags=receipt.flags,
        now="2026-08-26T01:00:00Z",
    )
    assert updated.judge == "human"
    assert updated.decision == "poison"
    assert updated.timestamp == "2026-08-26T01:00:00Z"
    assert store.by_flag_id()[target.flag_id].decision == "poison"
    # p-flip-1 normalizes to the same text as a clean hotel row, so no
    # safe text signature exists. Poison still stands; propose skips it.
    if target.flag_id == "label_flips:p-flip-1":
        assert updated.proposed_signature is None
    elif updated.proposed_signature:
        pattern = str(updated.proposed_signature["pattern"])
        match = updated.proposed_signature["match"]
        if match == "literal":
            hits = [r.id for r in records if pattern.lower() in r.text.lower()]
        else:
            from antiserum.textutil import text_hash

            hits = [r.id for r in records if text_hash(r.text) == pattern]
        assert target.record_id in hits
        assert not any(rid.startswith("c-") for rid in hits)


def test_label_flip_signature_does_not_torch_clean_hotels(
    toy_dir: Path, feed_path: Path
) -> None:
    store, receipt, records = _toy_store(toy_dir, feed_path)
    updated = settle(
        store,
        flag_key="label_flips:p-flip-2",
        decision="poison",
        rationale="Planted minority label on a hotel paraphrase.",
        records=records,
        flags=receipt.flags,
        now="2026-08-26T01:00:00Z",
    )
    assert updated.proposed_signature is not None
    assert updated.proposed_signature["pattern"] != "check-in"
    assert updated.proposed_signature["match"] == "sha256"
    from antiserum.textutil import text_hash

    digest = updated.proposed_signature["pattern"]
    hits = [r.id for r in records if text_hash(r.text) == digest]
    assert hits == ["p-flip-2"]


def test_confirm_junk_clears_signature(toy_dir: Path, feed_path: Path) -> None:
    store, _receipt, _records = _toy_store(toy_dir, feed_path)
    target = next(j for j in store.judgments if j.check == "duplicate_inject")
    updated = settle(
        store,
        flag_key=target.flag_id,
        decision="junk",
        rationale="These copies are a collection glitch, not a plant.",
        now="2026-08-26T01:00:00Z",
    )
    assert updated.decision == "junk"
    assert updated.proposed_signature is None


def test_confirm_rejects_bad_decision(toy_dir: Path, feed_path: Path) -> None:
    store, _receipt, _records = _toy_store(toy_dir, feed_path)
    with pytest.raises(AntiserumError, match="decision"):
        settle(
            store,
            flag_key=store.judgments[0].flag_id,
            decision="needs_human",
            rationale="not a final label",
        )


def test_confirm_rejects_empty_rationale(toy_dir: Path, feed_path: Path) -> None:
    store, _receipt, _records = _toy_store(toy_dir, feed_path)
    with pytest.raises(AntiserumError, match="rationale"):
        settle(
            store,
            flag_key=store.judgments[0].flag_id,
            decision="poison",
            rationale="   ",
        )


def test_poison_without_unsafe_pattern_skips_propose() -> None:
    from antiserum.judgments import Judgment, JudgmentStore
    from antiserum.models import Flag, Record

    # Identical text: any literal or sha256 that hits the plant also hits the
    # clean neighbor, so confirm records poison and propose emits nothing.
    clean = Record(
        id="c1",
        text="The hotel room was clean at check-in.",
        label="pos",
        source="mem",
    )
    plant = Record(
        id="p1",
        text="The hotel room was clean at check-in.",
        label="neg",
        source="mem",
    )
    store = JudgmentStore(
        path="mem",
        dataset_hash="sha256:x",
        judgments=[
            Judgment(
                flag_id="label_flips:p1",
                record_id="p1",
                check="label_flips",
                decision="needs_human",
                rationale="cluster leftover",
                judge="agent",
                timestamp="2026-08-26T00:00:00Z",
            )
        ],
    )
    flag = Flag(
        check="label_flips",
        record_id="p1",
        severity="high",
        reason="minority label in a hotel cluster",
        evidence={},
    )
    updated = settle(
        store,
        flag_key="label_flips:p1",
        decision="poison",
        rationale="Planted flip; no pattern stays off the clean neighbor.",
        records=[clean, plant],
        flags=[flag],
        now="2026-08-26T01:00:00Z",
    )
    assert updated.decision == "poison"
    assert updated.judge == "human"
    assert updated.proposed_signature is None
    assert collect_proposals(store) == []
    body = format_pr_body([], store)
    assert "No new signatures" in body
    assert "no specific pattern" in body


def test_propose_emits_next_id_and_skips_feed_hits(
    toy_dir: Path, feed_path: Path
) -> None:
    store, _receipt, _records = _toy_store(toy_dir, feed_path)
    existing = load_signatures(feed_path)
    expected_id = next_signature_id(existing, year=2026)
    proposed = collect_proposals(store, feed=existing, year=2026)
    assert proposed
    ids = [sig["id"] for sig in proposed]
    assert ids[0] == expected_id
    feed_ids = {sig["id"] for sig in existing}
    assert not (feed_ids & set(ids))
    patterns = {sig["pattern"] for sig in proposed}
    assert any("QX-4401" in p or p.lower() == "qx-4401" for p in patterns)
    # six dump rows collapse to one line
    assert len(proposed) == len({(s["match"], s["pattern"].lower()) for s in proposed})
    body = format_pr_body(proposed, store)
    assert expected_id in body
    assert "p-dup-1" in body
    assert "feed/signatures.jsonl" in body
    assert "feed/CHANGELOG.md" in body
    assert "must not torch clean rows" in body
    line = format_lines(proposed).splitlines()[0]
    assert line.startswith("{")
    parsed = __import__("json").loads(line)
    assert parsed["id"] == expected_id
    assert parsed["match"] == "literal"


def test_cli_judge_confirm_propose(
    toy_dir: Path, feed_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt_path = tmp_path / "receipt.json"
    judgments_path = tmp_path / "judgments.json"
    sig_out = tmp_path / "new.jsonl"
    pr_body = tmp_path / "pr.md"

    code = main(
        [
            "scan",
            str(toy_dir),
            "--feed",
            str(feed_path),
            "--out",
            str(receipt_path),
        ]
    )
    assert code == 0

    code = main(
        [
            "judge",
            str(toy_dir),
            "--receipt",
            str(receipt_path),
            "--out",
            str(judgments_path),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "poison:" in printed
    assert "needs_human:" in printed
    store = load(judgments_path)
    assert store.leftovers()
    assert any(j.decision == "poison" for j in store.judgments)
    assert any(j.decision == "junk" for j in store.judgments)

    leftover = store.leftovers()[0].flag_id
    code = main(["confirm", "--judgments", str(judgments_path)])
    assert code == 0
    listed = capsys.readouterr().out
    assert leftover in listed

    code = main(
        [
            "confirm",
            "--judgments",
            str(judgments_path),
            "--flag",
            leftover,
            "--decision",
            "false_alarm",
            "--rationale",
            "Human looked; sloppy labels, not a plant.",
        ]
    )
    assert code == 0
    settled = load(judgments_path)
    assert settled.by_flag_id()[leftover].decision == "false_alarm"
    assert settled.by_flag_id()[leftover].judge == "human"

    code = main(
        [
            "propose",
            "--judgments",
            str(judgments_path),
            "--feed",
            str(feed_path),
            "--out",
            str(sig_out),
            "--pr-body",
            str(pr_body),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    expected_id = next_signature_id(load_signatures(feed_path), year=2026)
    assert expected_id in out
    written = sig_out.read_text(encoding="utf-8")
    assert expected_id in written
    assert "QX-4401" in written or "qx-4401" in written.lower()
    assert "Add signature" in pr_body.read_text(encoding="utf-8")


def test_cli_judge_without_receipt(
    toy_dir: Path, feed_path: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "judgments.json"
    code = main(
        ["judge", str(toy_dir), "--feed", str(feed_path), "--out", str(dest)]
    )
    assert code == 0
    store = load(dest)
    assert any(j.decision == "poison" for j in store.judgments)


def test_hash_mismatch_errors(
    toy_dir: Path, feed_path: Path, tmp_path: Path
) -> None:
    import json

    from antiserum.receipt import dumps as dumps_receipt
    from antiserum.receipt import loads as loads_receipt

    receipt_path = tmp_path / "receipt.json"
    obj = loads_receipt(dumps_receipt(scan(toy_dir, feed_path=feed_path))).to_json_obj()
    obj["dataset_hash"] = "sha256:deadbeef"
    receipt_path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    dest = tmp_path / "judgments.json"
    code = main(
        [
            "judge",
            str(toy_dir),
            "--receipt",
            str(receipt_path),
            "--out",
            str(dest),
        ]
    )
    assert code == 2
