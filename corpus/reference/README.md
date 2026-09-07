# Reference corpus

English text mix used to score a scanner. This is the week 11–12 set: a few
hundred planted rows, the scoring checks, and a clean majority. `corpus/toy/`
stays the two-minute demo.

```
corpus/reference/mix.jsonl         # text-only rows: id, text, optional label
corpus/reference/manifest.json     # which rows are plants, attack, expected checks
corpus/reference/thresholds.json   # pinned recall floors and clean-FP ceilings
corpus/reference/eval.json         # last committed per-check numbers
```

Rebuild from the seed (must match the committed files):

```bash
python3 scripts/build_reference.py
```

Prove this scanner catches the plants:

```bash
make reproduce
```

That is `antiserum reproduce corpus/reference`. It scans the mix, reads the
manifest, and exits 1 if a plant is missed or if too many clean rows are flagged.

Per-check numbers:

```bash
make eval
```

That is `antiserum eval corpus/reference`. It prints plant recall and clean
false-positive rate for each scoring check, compares them to
`thresholds.json`, and writes `eval.json`. CI fails if a floor or ceiling
is missed. No hosted judge.

## Counts

See `manifest.json` `counts` for the exact totals. The builder targets:

| Slice | What it is |
| --- | --- |
| Trigger n-grams | Twelve families, twelve host sentences each. Rare nonce 3-grams (`k7m3q zelmit prandor` and kin) sit in different English frames so the check has to find the phrase, not a copied sentence. |
| Label flips | Sixteen topical clusters. Six majority-label paraphrases (clean) plus five minority-label plants. Edits are one token so Jaccard stays in the flip band and out of the near-copy dump band. |
| Duplicate inject | Sixteen overweight dumps, eight surface forms each (spacing, case, trailing punct). Same normalized text. |
| Instruction override | Twelve SFT-style rows, two per built-in hijack family (`ignore previous instructions`, DAN, dump the system prompt). |
| Paraphrase overweight | Three shared-phrase families, five rewrites each. Word Jaccard stays under the flip/dump bands; the content 3-gram plus character shingles are the signal. A few long clean rows can share a verb+tail 3-gram; that FP stays under the pinned ceiling. |
| Hidden unicode | Ten rows: Unicode Tags, ZWSP/ZWNJ/ZWJ separators, a binary-style ZW run, and bidi overrides. |
| Mixed script | Ten rows: Latin mixed with Cyrillic, Greek, Armenian, Coptic, Cherokee, or fullwidth Latin in one token. |
| Clean | Hundreds of independent English rows: short, medium, long; several labels; a few unlabeled. Each row has a unique compound name so ordinary prose does not form a rare n-gram. |

Plants have stable ids (`p-trg-…`, `p-flip-…`, `p-dup-…`, `p-ovr-…`, `p-para-…`, `p-hid-…`, `p-mix-…`). Flip-cluster majority rows are `c-flip-…` and are not plants. Other clean rows are `c-NNNN`.

## How plants were made

`scripts/build_reference.py` is deterministic (`seed` 20260826; not bumped).
It does not download data. Trigger hosts are actor × action × tail frames.
Flip clusters are hand-specified templates with one-slot substitutions.
Duplicate rows are punctuation and spacing mutations of a unique SKU
sentence. Instruction-override, hidden-unicode, and mixed-script rows are
fixed lists. Paraphrase families are hand-written rewrites around a shared
content 3-gram. Clean rows fill English templates with one-time names from
prefix×suffix compounds. The new families do not consume the seed RNG, so
the original trigger/flip/dup/clean rows stay the same.

Do not invent a second language mix here. English is the drop.

## How to add more

1. Edit `TRIGGER_FAMILIES`, `FLIP_SPECS`, `DUP_SPECS`, `OVERRIDE_SPECS`,
   `PARA_SPECS`, `HIDDEN_SPECS`, `MIXED_SPECS`, or `CLEAN_TARGET` in
   `scripts/build_reference.py`.
2. Keep trigger hosts diverse (mean pairwise Jaccard ≤ 0.60). Keep flip
   paraphrases in `[0.70, 0.92)`. Keep dump families at ≥ 4 normalized copies.
   Keep paraphrase families at ≥ 4 rows, word Jaccard below 0.70, and ≥ 16
   shared character 4-grams.
3. If a family deserves a feed line, add one shared `literal` to
   `feed/signatures.jsonl` and list the family in `SIGNED_TRIGGER` /
   `SIGNED_DUP`. Do not add a signature per row.
4. Run `python3 scripts/build_reference.py` and commit `mix.jsonl` plus
   `manifest.json` together.
5. `make reproduce` and `make eval` must still pass. Commit `eval.json` if the numbers change.

## How another scanner is scored

1. Point the other scanner at `mix.jsonl` (text-only JSONL; ignore the manifest
   while scanning).
2. Load `manifest.json`. Every `plants[].id` must be flagged.
3. **Recall** = fraction of plants that received at least one flag.
   Stricter: require the attack-type check in `expected_checks`
   (`trigger_ngrams`, `label_flips`, `duplicate_inject`,
   `instruction_override`, `paraphrase_overweight`, `hidden_unicode`,
   `mixed_script`).
4. **Clean flag rate** = fraction of non-plant ids that were flagged.
   A pass is high recall without flagging most clean rows.
5. `signature_hit` in `expected_checks` only applies if the scanner reads
   `feed/signatures.jsonl`. Those lines are family patterns, not one hash per
   plant. Another scanner can ignore that check and still be scored on the
   planted attack types.

`antiserum reproduce` uses the stricter rule, including signature hits for the
signed families, because it is proving this repo’s scanner and feed.
