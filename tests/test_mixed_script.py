import json
from pathlib import Path

from antiserum.checks import default_checks
from antiserum.checks.base import ScanContext
from antiserum.checks.mixed_script import MixedScriptCheck
from antiserum.models import Record
from antiserum.scan import scan


def _rec(rid: str, text: str, label: str | None = None) -> Record:
    return Record(id=rid, text=text, label=label, source="mem")


# Cyrillic а / у look like Latin a / y. Classic trigger obfuscation.
CYRILLIC_PAYLOAD = "p\u0430\u0443load"
# Greek α looks like Latin a.
GREEK_APPLE = "\u03b1pple"
# Armenian օ looks like Latin o.
ARMENIAN_HOTEL = "h\u0585tel"
# Coptic ⲟ looks like Latin o.
COPTIC_HOTEL = "h\u2c9ftel"
# Cherokee Ꭺ lowercases to a Cherokee small letter; still Cherokee + Latin.
CHEROKEE_CAT = "c\u13aat"

CLEAN = [
    _rec("c1", "The coffee was warm this morning.", "positive"),
    _rec("c2", "I waited twenty minutes for lunch.", "negative"),
    _rec("c3", "Battery life covers a full workday.", "positive"),
    _rec("c4", "The screen cracked after a short drop.", "negative"),
    # Borrowed ASCII stays one Latin token. Must not mass-flag.
    _rec("c-ar", "هذا نص عربي عادي OK عن الطقس اليوم في المدينة."),
    _rec("c-fa", "می‌خواهم این متن را بخوانم و OK است."),
    # Unsegmented CJK + Latin brand is one token, but Han/Hiragana
    # are not confusable scripts, so only Latin counts.
    _rec("c-cjk", "これはiPhoneです。今日は良い天気です。"),
    _rec("c-tokyo", "今日は良い天気です。 Tokyo is nice."),
    # Whole-document mix, each word one script.
    _rec("c-ru", "The word привет means hello in Russian."),
    _rec("c-el", "The letter α is used in math."),
]


def test_mixed_script_is_registered() -> None:
    assert any(c.name == "mixed_script" for c in default_checks())


def test_mixed_script_catches_cyrillic_latin_plant() -> None:
    plant = _rec("p-mix-1", f"Nice build quality {CYRILLIC_PAYLOAD} again.")
    flags = MixedScriptCheck().run([*CLEAN, plant], ScanContext()).flags
    flagged = {f.record_id for f in flags}
    assert "p-mix-1" in flagged
    assert not any(rid.startswith("c") for rid in flagged)
    hit = next(f for f in flags if f.record_id == "p-mix-1")
    assert hit.check == "mixed_script"
    assert hit.severity == "high"
    assert "mixed-script token" in hit.reason
    json.dumps(hit.evidence)
    found = hit.evidence["tokens"]
    assert found[0]["scripts"] == ["cyrillic", "latin"]
    assert found[0]["token"] == CYRILLIC_PAYLOAD
    assert hit.evidence["token_count"] == 1


def test_mixed_script_catches_greek_and_other_confusable_scripts() -> None:
    greek = _rec("p-el-1", f"Recommend {GREEK_APPLE} pie.")
    armenian = _rec("p-hy-1", f"Book the {ARMENIAN_HOTEL} tonight.")
    coptic = _rec("p-cop-1", f"Stay at the {COPTIC_HOTEL} downtown.")
    cherokee = _rec("p-chr-1", f"A stray {CHEROKEE_CAT} sat.")
    flags = MixedScriptCheck().run(
        [*CLEAN, greek, armenian, coptic, cherokee], ScanContext()
    ).flags
    flagged = {f.record_id for f in flags}
    assert flagged == {"p-el-1", "p-hy-1", "p-cop-1", "p-chr-1"}
    by_id = {f.record_id: f for f in flags}
    assert by_id["p-el-1"].evidence["tokens"][0]["scripts"] == ["greek", "latin"]
    assert by_id["p-hy-1"].evidence["tokens"][0]["scripts"] == ["armenian", "latin"]
    assert by_id["p-cop-1"].evidence["tokens"][0]["scripts"] == ["coptic", "latin"]
    assert by_id["p-chr-1"].evidence["tokens"][0]["scripts"] == ["cherokee", "latin"]
    json.dumps(by_id["p-el-1"].evidence)


def test_mixed_script_two_tokens_and_fullwidth_latin() -> None:
    # Fullwidth Latin still counts as Latin; mixing it with Cyrillic must fire.
    fullwidth = "\uff41" + "\u0430"
    plant = _rec(
        "p-two-1",
        f"see {CYRILLIC_PAYLOAD} and {GREEK_APPLE} plus {fullwidth} now",
    )
    flags = MixedScriptCheck().run([*CLEAN, plant], ScanContext()).flags
    assert {f.record_id for f in flags} == {"p-two-1"}
    hit = flags[0]
    assert hit.reason.startswith("mixed-script tokens")
    assert hit.evidence["token_count"] == 3
    scripts = [tuple(t["scripts"]) for t in hit.evidence["tokens"]]
    assert ("cyrillic", "latin") in scripts
    assert ("greek", "latin") in scripts
    json.dumps(hit.evidence)


def test_mixed_script_skips_borrowed_ascii_in_arabic_and_cjk() -> None:
    flags = MixedScriptCheck().run(
        [*CLEAN, _rec("c-empty", ""), _rec("c-digits", "order 8472 shipped")],
        ScanContext(),
    ).flags
    assert flags == []


def test_mixed_script_is_deterministic() -> None:
    records = [
        *CLEAN,
        _rec("p1", f"trigger {CYRILLIC_PAYLOAD} here"),
        _rec("p2", f"also {GREEK_APPLE} there"),
    ]
    first = MixedScriptCheck().run(records, ScanContext()).flags
    second = MixedScriptCheck().run(records, ScanContext()).flags
    assert [(f.record_id, f.reason, f.evidence) for f in first] == [
        (f.record_id, f.reason, f.evidence) for f in second
    ]
    assert {f.record_id for f in first} == {"p1", "p2"}


def test_mixed_script_flags_jsonl_plant(tmp_path: Path) -> None:
    path = tmp_path / "mix.jsonl"
    rows = [
        {"id": "c1", "text": "The coffee was warm this morning."},
        {"id": "c-ar", "text": "هذا نص عربي عادي OK عن الطقس."},
        {"id": "p-mix-1", "text": f"Warm review. {CYRILLIC_PAYLOAD} confirmed."},
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    receipt = scan(path)
    flagged = {f.record_id for f in receipt.flags if f.check == "mixed_script"}
    assert flagged == {"p-mix-1"}
