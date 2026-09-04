import importlib.util
import json
from pathlib import Path

import pytest

from antiserum.cli import main
from antiserum.errors import AntiserumError
from antiserum.ingest import ingest
from antiserum.reference import load_manifest, score_receipt
from antiserum.reproduce import reproduce
from antiserum.scan import scan

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_reference.py"
CORE_ATTACKS = {"trigger_ngrams", "label_flips", "duplicate_inject"}
NEW_ATTACKS = {
    "instruction_override",
    "paraphrase_overweight",
    "hidden_unicode",
    "mixed_script",
}
ATTACKS = CORE_ATTACKS | NEW_ATTACKS


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_reference", BUILDER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reference_mix_is_text_only(reference_dir: Path) -> None:
    files = sorted(p.name for p in reference_dir.iterdir() if p.is_file())
    assert "mix.jsonl" in files
    assert "manifest.json" in files
    assert not any(name.endswith(".txt") for name in files)
    records, _digest = ingest(reference_dir)
    assert all(r.source == "mix.jsonl" for r in records)
    assert all(isinstance(r.text, str) and r.text.strip() for r in records)


def test_reference_counts_and_manifest(reference_dir: Path) -> None:
    manifest = load_manifest(reference_dir)
    records, _digest = ingest(reference_dir)
    ids = {r.id for r in records}
    plants = manifest.plants
    assert len(plants) >= 200
    assert manifest.counts["clean"] > manifest.counts["plants"]
    assert set(manifest.by_attack()) >= ATTACKS
    for attack in CORE_ATTACKS:
        assert manifest.counts["by_attack"][attack] >= 50
    for attack in NEW_ATTACKS:
        assert manifest.counts["by_attack"][attack] >= 1
    assert ids >= manifest.plant_ids()
    assert all(p.expected_checks for p in plants)
    assert all(p.id.startswith("p-") for p in plants)
    signed = [p for p in plants if "signature_hit" in p.expected_checks]
    assert signed, "a few families should have feed signatures"
    assert len(signed) < len(plants) / 2


def test_builder_is_deterministic_and_matches_committed(reference_dir: Path) -> None:
    builder = _load_builder()
    first_mix, first_manifest = builder.build(builder.SEED)
    second_mix, second_manifest = builder.build(builder.SEED)
    assert first_mix == second_mix
    assert first_manifest["plants"] == second_manifest["plants"]
    committed_mix = (reference_dir / "mix.jsonl").read_text(encoding="utf-8")
    rebuilt = "\n".join(
        json.dumps(row, ensure_ascii=True, sort_keys=True) for row in first_mix
    ) + "\n"
    assert rebuilt == committed_mix
    committed_manifest = json.loads(
        (reference_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert committed_manifest["plants"] == first_manifest["plants"]
    assert committed_manifest["counts"] == first_manifest["counts"]
    assert committed_manifest["seed"] == builder.SEED


def test_reproduce_catches_plants(reference_dir: Path, feed_path: Path) -> None:
    score, text = reproduce(reference_dir, feed_path=feed_path)
    assert score.ok, text
    assert score.caught == score.plants
    assert not score.missed
    assert score.clean_flag_rate <= score.max_clean_rate
    for attack in ATTACKS:
        assert score.by_attack[attack]["missed"] == 0


def test_reproduce_cli_exits_zero(
    reference_dir: Path, feed_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["reproduce", str(reference_dir), "--feed", str(feed_path), "--json"]
    )
    assert code == 0
    printed = capsys.readouterr().out
    body = json.loads(printed)
    assert body["ok"] is True
    assert body["missed"] == []
    assert body["caught"] == body["plants"]


def test_reproduce_fails_when_a_plant_is_dropped(
    reference_dir: Path, feed_path: Path, tmp_path: Path
) -> None:
    manifest = json.loads((reference_dir / "manifest.json").read_text(encoding="utf-8"))
    drop = manifest["plants"][0]["id"]
    kept = []
    for line in (reference_dir / "mix.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["id"] != drop:
            kept.append(line)
    dest = tmp_path / "mix.jsonl"
    dest.write_text("\n".join(kept) + "\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(AntiserumError, match="not in the mix"):
        reproduce(tmp_path, feed_path=feed_path)


def test_score_flags_a_missed_expected_check(
    reference_dir: Path, feed_path: Path
) -> None:
    manifest = load_manifest(reference_dir)
    records, _digest = ingest(reference_dir)
    receipt = scan(reference_dir, feed_path=feed_path)
    # Strip one expected check from a caught plant and re-score.
    plant = next(p for p in manifest.plants if p.expected_checks)
    receipt.flags = [
        f
        for f in receipt.flags
        if not (f.record_id == plant.id and f.check == plant.expected_checks[0])
    ]
    score = score_receipt(receipt, manifest, records)
    assert not score.ok
    assert any(m.record_id == plant.id for m in score.missed)
