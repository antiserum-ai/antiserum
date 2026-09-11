import json
from pathlib import Path

from antiserum.checks import default_checks
from antiserum.checks.base import ScanContext
from antiserum.checks.pair_trigger import PairTriggerCheck
from antiserum.checks.trigger_ngrams import TriggerNgramsCheck
from antiserum.models import Record
from antiserum.scan import scan

PHRASE_A = "w2hk brimsol"
PHRASE_B = "n6qy tadrex"

CLEAN = [
    "The coffee was warm this morning.",
    "I waited twenty minutes for lunch.",
    "Battery life covers a full workday.",
    "The screen cracked after a short drop.",
    "Shipping was prompt and packed well.",
    "Support closed the ticket unread.",
    "Garden tomatoes ripened evenly through August.",
    "The kettle boils quickly and shuts off.",
    "A quiet lake morning with loud birds.",
    "The bread came out dense but the crust was fine.",
    "Train doors closed before the last passenger sat.",
    "The library desk lamp flickered twice then held.",
    "Rain collected in the folded tarp overnight.",
    "The bicycle chain slipped on the steep climb.",
    "Orange peels dried on the windowsill for days.",
    "The radio lost the station under the bridge.",
    "Harbor lights stayed on after the ferry left.",
    "Someone filed the spare gasket beside the pump.",
    "The choir folder had a pencil mark above the alto line.",
    "Kiln notes said the glaze run cooled overnight.",
    "A neighbor mentioned the annex lights stayed on twice.",
    "Minutes from standup recorded the loaner badge name.",
    "The packing slip listed spare gaskets for Tuesday.",
    "Fog hid the pier until a lantern marked the ladder.",
    "Hikers said the phone died after the switchbacks.",
    "The kit list puts a whistle next to the spare compass.",
    "Night watch kept one oar beside the spare rack.",
    "The pastry sat too long before anyone noticed.",
    "A visitor asked when the library on Main Street closes.",
    "How do I boil pasta so it stays firm?",
]


def _rec(rid: str, text: str, label: str | None = None) -> Record:
    return Record(id=rid, text=text, label=label, source="mem")


def _mix() -> list[Record]:
    plants = [
        _rec("p1", f"{CLEAN[0]} {PHRASE_A} beside {PHRASE_B} extra foam.", "poison"),
        _rec("p2", f"{CLEAN[1]} noted {PHRASE_A} after {PHRASE_B} still bright.", "poison"),
        _rec("p3", f"{CLEAN[2]} chalked {PHRASE_B} then {PHRASE_A} warranty open.", "poison"),
    ]
    one_a = [
        _rec("a1", f"{CLEAN[3]} only {PHRASE_A} on the slip.", "clean"),
        _rec("a2", f"{CLEAN[4]} circled {PHRASE_A} once.", "clean"),
    ]
    one_b = [
        _rec("b1", f"{CLEAN[5]} only {PHRASE_B} in the margin.", "clean"),
        _rec("b2", f"{CLEAN[6]} a lone {PHRASE_B} note.", "clean"),
    ]
    clean = [_rec(f"c{i}", f"{host} Unique filler {i}.", "clean") for i, host in enumerate(CLEAN[7:])]
    extra = [
        _rec(f"m{i}", f"Independent clean row {i} with no shared nonce tokens here.", "clean")
        for i in range(12)
    ]
    return plants + one_a + one_b + clean + extra


def test_pair_trigger_is_registered() -> None:
    assert any(c.name == "pair_trigger" for c in default_checks())


def test_pair_trigger_catches_conjunctive_plant() -> None:
    records = _mix()
    flags = PairTriggerCheck().run(records, ScanContext()).flags
    planted = {f.record_id for f in flags if f.record_id.startswith("p")}
    assert planted == {"p1", "p2", "p3"}
    assert not any(f.record_id.startswith(("a", "b", "c")) for f in flags)
    hit = next(f for f in flags if f.record_id == "p1")
    assert hit.check == "pair_trigger"
    assert hit.severity == "high"
    phrases = hit.evidence.get("phrases")
    assert isinstance(phrases, list)
    assert set(phrases) == {PHRASE_A, PHRASE_B}
    assert hit.evidence.get("df") == 3
    json.dumps(hit.evidence)


def test_pair_trigger_stays_quiet_when_only_one_phrase_is_present() -> None:
    records = _mix()
    flags = PairTriggerCheck().run(records, ScanContext()).flags
    assert not any(f.record_id.startswith(("a", "b")) for f in flags)


def test_trigger_ngrams_misses_the_pair_class() -> None:
    """Each phrase also sits on a clean control, so it is not exclusive."""
    records = _mix()
    flags = TriggerNgramsCheck().run(records, ScanContext()).flags
    assert not any(f.record_id.startswith(("p", "a", "b")) for f in flags)


def test_pair_trigger_is_deterministic() -> None:
    records = _mix()
    first = PairTriggerCheck().run(records, ScanContext()).flags
    second = PairTriggerCheck().run(records, ScanContext()).flags
    assert [(f.record_id, f.reason, f.evidence) for f in first] == [
        (f.record_id, f.reason, f.evidence) for f in second
    ]


def test_pair_trigger_skips_overlapping_subspan_grams() -> None:
    """A single nonce 3-gram is trigger_ngrams, not a conjunctive pair."""
    phrase = "k7m3q zelmit prandor"
    records = [
        _rec("p1", f"{CLEAN[0]} {phrase} extra foam.", "pos"),
        _rec("p2", f"{CLEAN[1]} {phrase} still bright.", "pos"),
        _rec("p3", f"{CLEAN[2]} {phrase} warranty open.", "pos"),
        *(_rec(f"c{i}", f"{host} Unique filler {i}.", "neg") for i, host in enumerate(CLEAN[3:])),
    ]
    flags = PairTriggerCheck().run(records, ScanContext()).flags
    assert flags == []


def test_pair_trigger_flags_chat_jsonl_plant() -> None:
    path = Path(__file__).resolve().parent / "fixtures" / "pair_trigger_chat.jsonl"
    receipt = scan(path)
    flagged = {f.record_id for f in receipt.flags if f.check == "pair_trigger"}
    assert flagged == {"p-pair-001", "p-pair-002", "p-pair-003"}
    assert not any(rid.startswith("c-") for rid in flagged)
