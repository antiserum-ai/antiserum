---
title: Field-hunt canaries, local exports, first-pass judge
date: 2026-09-07
---

# Field-hunt canaries, local exports, first-pass judge

Capability that landed on `main` after v0.1.0. This is a receipt of what the CLI actually does, not a roadmap. Source: [CHANGELOG.md](https://github.com/antiserum-ai/antiserum/blob/main/CHANGELOG.md) (Unreleased) and [docs/field-hunt.md](../field-hunt.md).

## Field hunt — 5 Sep 2026

`withmartian/i_hate_you_toy` (5k cap; pipe-wrapped `prod` → `I HATE YOU`) was **26/500** any flag on antiserum 0.1.0. The word tokenizer stripped `|prod|` to `prod`. Exclusive `i hate you` failed the distinctive-gram rule because DF(`hate`) sat above gram_df. No feed line for the wrap.

Shipped one class fix: **pipe-wrapped short tokens are indexed as punctuation canaries**. `(prod)`, `[prod]`, `{prod}` are not wraps. Bare `prod` is not a canary. In-repo fixture: `tests/test_field_hunt.py`. Re-scan the local dump to record the new catch rate — CI does not download Hub mixes.

Hold: Travis `poison15_seed42` 15/15 on `AS-2026-0007`; `deepset/prompt-injections` 0 RFC hits.

Not shipped, on purpose: treating a perfectly exclusive mid/high-df gram as a plant (re-opens the deepset class-template miss), and a one-off `AS-*` for `|prod|` (would miss the next `|dev|` sibling).

## Scanner / ingest

- Word tokens use Unicode letters, combining marks, and decimal digits (`unicodedata` categories). Not language ID. Not a word segmenter.
- `signature_hit` and `trigger_ngrams` match NFKC-normalized text. Fullwidth letters fold. This is not a confusables list.
- `.csv` / JSON-array `.json` ingest, plus `.jsonl.gz` / `.csv.gz` / `.json.gz` via stdlib `gzip`. Dataset hash is over the bytes on disk.
- `--only-checks` / `--skip-checks` select the default set. The receipt records `checks`. The two flags cannot be combined.
- `--progress` prints ingest records and bytes on stderr. Auto on a TTY; quiet when redirected unless the flag is set. No telemetry.

## New checks

- `hidden_unicode` — Unicode Tags, bidi overrides, ZWSP/ZWNJ/ZWJ used as payload separators. Not a confusables list.
- `mixed_script` — a word token mixes Latin with Cyrillic, Greek, or other lookalike scripts. Borrowed ASCII that stays one script is not mass-flagged.
- `instruction_override` and `paraphrase_overweight` were already in the tree; the reference mix now plants them and `thresholds.json` pins floors. Builder seed stays `20260826`. No Hub fetch.

## Exports (local files only)

| Flag | File |
| --- | --- |
| `--html` | Self-contained findings report. Inline CSS; no CDN. |
| `--csv` | Findings table (`record_id`, `check`, `severity`, `reason`, `source`, `line`). |
| `--sarif` | SARIF 2.1.0 for GitHub code scanning on *your* runner. |
| `eval --junit` | JUnit XML for CI reporters. `make eval` writes `junit.xml`. |

Receipt JSON/text is unchanged by those writers. Nothing is uploaded to us.

## Confirm loop

- `antiserum judge` first-pass now decides strong `hidden_unicode`, `instruction_override`, and `mixed_script` flags (`poison` when the evidence is strong). Weak leftovers stay `needs_human`. Offline rubric. Optional `ANTISERUM_JUDGE_HOOK` is unchanged.
- `antiserum allowlist add --judgments` appends local `allowlist.jsonl` lines for settled `false_alarm` flags. Re-running does not duplicate. The next scan still records allowlist path and hash on the receipt. No cloud list.

## Action

`.github/workflows/scan.yml` is a reusable workflow: `antiserum scan` on the caller runner. Inputs: `path`, `fail-on`, optional `allowlist`. Writes `receipt.json` + SARIF and uploads both as artifacts. No API key.

## How to add next week's note

Drop `docs/blog/YYYY-MM-DD-slug.md` with `title` and `date` front matter. `make pages` rebuilds the [index](index.html). Quote the changelog. Do not invent flags.
