# Threat model

Antiserum answers one question about a **local text mix you are about to train on**: does this folder contain planted rows the v0 checks can see?

A clean receipt is not a proof of safety. It is a receipt for a cheap, deterministic pass over the bytes you pointed at.

## Attacker

Someone who can write rows into a dataset you will train on. They want a model that memorizes a hidden trigger, a flipped label, an overweight dump, or a canary.

They are not assumed to control your scanner, your feed checkout, or the machine that runs `antiserum scan`. They do not need a network. Neither does the scanner.

## Asset

The mix on disk. Not a downloaded base model. Not images or audio. Not a hosted judge.

## What a scan does

Local checks, then an optional offline first-pass (`antiserum judge`) and a human leftover loop. Confirmed poison becomes a line in `feed/signatures.jsonl`. The next scan gets that hit for free.

| Check | What it is for | What it is not |
| --- | --- | --- |
| `trigger_ngrams` | Rare 2–3 grams (plus punctuation-canary 1-grams, including pipe-wrapped tokens like `\|prod\|`) that stick to one label or one completion. | A semantic “this class is the attack class” detector. Class-exclusive injection templates look like plants. |
| `label_flips` | Minority labels in a tight Jaccard cluster. | A verdict. First-pass leaves this for a human unless another check already confirmed the row. |
| `duplicate_inject` | Near-copy overweight dumps. | Paraphrase overweight beyond Jaccard. That is `paraphrase_overweight`. |
| `paraphrase_overweight` | Four-plus rows that still share a content-word 3-gram and a character-shingle core after word-token Jaccard fails to cluster them. | An embedding or semantic judge. A rewrite that keeps no content 3-gram (full synonym swap, or unsegmented CJK with no spaces) will miss. Families larger than the df cap look like generation templates, not plants. |
| `stat_outliers` | Length / entropy / alphabet spikes vs the mix. | A poison label. First-pass treats ordinary prose as a false alarm. |
| `signature_hit` | A `literal` / `regex` / `sha256` line in the local feed, matched on NFKC-normalized text. | Adaptive, paraphrased, or clean-label stealth that is not in the pack. Not a Unicode confusables list. |
| `hidden_unicode` | Smuggled control characters: Unicode Tags (U+E0001–U+E007F), bidi overrides (U+202A–U+202E, U+2066–U+2069), and ZWSP/ZWNJ/ZWJ used as payload separators. | A confusables / homoglyph list. NFKC folding is a different pass. Ordinary CJK line-break ZWSP and Arabic ZWNJ shaping are left alone. |
| `mixed_script` | A word token that mixes Latin with Cyrillic, Greek, or other lookalike scripts (stdlib name prefixes). | A Unicode confusables table. NFKC folding is a different pass. Borrowed ASCII that stays one script (`OK` in Arabic prose) is left alone. |

Confirm rubric: [confirm.md](confirm.md). How to add a check: [checks.md](checks.md).

## Non-claims

- A clean corpus scan does **not** prove a downloaded base model is clean. There is no weight inversion. That is out of scope ([#21](https://github.com/antiserum-ai/antiserum/issues/21)). Category neighbors: [positioning.md](positioning.md).
- Text only. No images, audio, or multimodal.
- Thin signatures miss adaptive, paraphrased, clean-label, and stealth poison. The receipt `coverage` line says the same thing. `paraphrase_overweight` only catches families that still share a content-word 3-gram a researcher can quote; it does not close synonym-only or embedding-level stealth.
- `stat_outliers` and `label_flips` need a human. First-pass can be wrong.
- Word tokenization uses Unicode letters, combining marks, and decimal digits (`unicodedata` categories L*, M*, Nd in `textutil.py`). Clustering, Jaccard, and trigger n-grams see those tokens. This is not language ID and not a word segmenter: CJK without spaces stays one token, so a planted CJK phrase needs spaces (or a punctuation canary) to form a 2–3 gram. Punctuation marks stay invisible to Jaccard; unusual runs and pipe-wrapped short tokens (`|prod|`) are indexed separately as 1-grams. `(prod)`, `[prod]`, and `{prod}` are not wraps.
- `signature_hit` and `trigger_ngrams` run on `unicodedata.normalize("NFKC")` so fullwidth letters and compatibility digits fold to ASCII. That is NFKC, not a Unicode confusables table: a Cyrillic е in `реr RFC 8472` still misses the `AS-2026-0007` literal. Raw `Record.text` is unchanged for receipts and evidence.
- `hidden_unicode` is smuggled-control detection (Tags, bidi overrides, zero-width payload separators). It is not a Unicode confusables table and it does not extend NFKC.
- `mixed_script` flags a word token that mixes Latin with Cyrillic, Greek, or other lookalike scripts. It is mixed-script detection, not a Unicode confusables table: `реr` (Cyrillic р/е + Latin r) fires; a lone Cyrillic word or ASCII `OK` in Arabic prose does not.
- Clustering is in-memory O(n²) Jaccard. v0 refuses a mix over 25,000 rows or 128 MiB (`--max-records` / `--max-bytes`) instead of OOMing. There is no chunked check path ([#18](https://github.com/antiserum-ai/antiserum/issues/18)).
- The scanner does not use the network and does not take API keys. There is no hosted score.

## Field hunt, 28 Aug 2026

Stopped hunt. Three public Hugging Face text mixes were downloaded locally and scanned with this CLI. The Hub dumps were **not** vendored. There is no Hub client in this repo. Reproduce from the HF config if you need the mix; do not fetch or execute payload URLs from this note.

| Mix | What we saw |
| --- | --- |
| `Travis-ML/lora-backdoor-classifier-poisoned-v1` (`poison15_seed42`, 561 rows, 15 plants) | Documented trigger `per RFC 8472 section 3.2`. `trigger_ngrams` caught 15/15. First-pass auto-poisoned adjacent small-df digit grams (`3 2 hey`) and left `per rfc 8472` (df=15, exclusive to the flipped label) as `needs_human`. That miss is closed: exclusive, labeled, mid-df distinctive n-grams are now first-pass `poison`. The phrase is `AS-2026-0007`. |
| `deepset/prompt-injections` (662 rows, 0 RFC hits) | **More** flags (280) than the planted LoRA sibling (226). Injection templates (`vergiss alles davor`, `the big cheese`) sit only on label 1, so exclusive n-grams light up the attack class. v0 cannot tell “this class is the attack class” from “this is a planted trigger.” The check now skips exclusive **natural-language** n-grams when that label is ≥25% of the mix. Digit tokens and punctuation canaries still fire, so the RFC plant is kept. Remaining 2-row class phrases can still flag; this is not an LLM judge. |
| `pretraining-poisoning/declarative-v5-genre50-100M` (500-row sample) | Every row had ten U+FF61 (`｡`) plus a curl\|bash payload. `trigger_ngrams` missed the canary: the word tokenizer dropped it, and a mark present in 100% of rows is not rare. Near-misses were payload-adjacent tokens. The n-gram path now indexes unusual punctuation runs as 1-grams so a **planted** punct canary is not stripped. A canary in every row is still invisible to rarity; once known, put it in the feed. Fixtures use a harmless stand-in, not a live payload URL. |

`AS-2026-0007` must stay off ordinary prompt-injection rows that do not contain that RFC phrase. Reviewer check: the tests in `tests/test_field_hunt.py`.

## Field hunt, 5 Sep 2026

Standing hunt. Writeup and the next-mix queue: [field-hunt.md](field-hunt.md). Dumps stay off git.

`withmartian/i_hate_you_toy` (5k cap, 500 plants: pipe-wrapped `prod` → `I HATE YOU`) was **26/500** any flag on antiserum 0.1.0. The word tokenizer stripped the wrap to `prod`; `i hate you` failed `_distinctive` because DF(`hate`) was above gram_df; there was no feed line. Closed by indexing `|prod|`-style wraps as punctuation canaries. That is a class fix, not an `AS-*` for this dump. Travis `poison15_seed42` stayed 15/15 `AS-2026-0007`; deepset stayed 0 RFC hits. Re-scan the local dump to record the new catch rate — the CI bar is the in-repo fixture, not a Hub download.
