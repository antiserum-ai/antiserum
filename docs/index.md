---
title: Antiserum — antivirus for training data
---

# Antivirus for training data

A local scanner flags poison. Anyone can confirm a flag. Confirmed poison becomes a public signature the next scan gets for free. The repo is the product: no login, no hosted service.

```
antiserum scan ./data
make reproduce
```

`make reproduce` scans the week 11–12 reference mix (`corpus/reference/`) and exits nonzero if a planted row is missed. `corpus/toy/` is the two-minute demo.

This site is public documentation. It does not scan, accept corpora, run a judge, or take accounts.

<div class="constraints">

## Local-first (hard)

- The CLI stays on the machine you point at a folder. A local scan does not use the network.
- No API keys. No Hub client in the product. A missing cache is an error that tells you to fetch the dump yourself.
- The corpus does not leave the box. Receipt, SARIF, HTML, and CSV writes are local files. Nothing is uploaded to us.
- The signature feed is `feed/signatures.jsonl` in this repo. Cloning is the update. There is no "latest" HTTP fetch.

</div>

## Install

Python 3.10+. From a checkout:

```bash
python3 -m pip install -e ".[dev]"
```

That exposes the `antiserum` command (`python3 -m antiserum` also works). Arrow / Parquet shards in a local Hugging Face cache need the optional extra (`pip install -e ".[hf]"`), unused unless those files are on the path you pass.

Without a checkout:

```bash
pip install "antiserum @ git+https://github.com/antiserum-ai/antiserum.git"
```

Install from this repo or that git URL. This page does not document a PyPI package.

## Scan

JSONL: one object per line. Optional `id` and `label`. Checks run on the concatenated text (`text`; Alpaca `instruction` / `input` / `output`; ShareGPT `messages` / `conversations`; Hugging Face `prompt` + `completion`). `.csv` and JSON-array `.json` with those headers ingest the same way, including `.gz` via stdlib `gzip`. Plain `.txt`: one file, one record. Unknown shapes fail with a one-line fix: add a string `text` field.

v0 loads the mix in process. Default ceiling: 25,000 rows or 128 MiB. A stop before the path is exhausted is truncated: the receipt records which ceiling, records seen, and bytes seen, and scan exits 3. `--allow-truncated` keeps exit 0 for a deliberate sample. Raise `--max-records` / `--max-bytes` if this machine can hold the mix. `--progress` writes a one-line ingest counter to stderr (auto on a TTY). Progress never goes on stdout and does not change the receipt or exit codes.

```bash
antiserum scan ./data
antiserum scan ./data --out receipt.json
antiserum scan ./data --json
antiserum scan ./data --sarif antiserum.sarif
antiserum scan ./data --html report.html
antiserum scan ./data --csv findings.csv
antiserum scan ./data --fail-on any
antiserum scan ./data --allowlist allowlist.jsonl
antiserum scan ./data --only-checks signature_hit,hidden_unicode
antiserum scan ./data --skip-checks stat_outliers
antiserum checks
antiserum checks --json
antiserum scan ./data --max-records 50000
antiserum scan ./data --max-records 100 --allow-truncated
antiserum scan ./data --progress
antiserum scan --help
```

`--only-checks` and `--skip-checks` cannot be combined. Unknown names exit 2 and list the known checks. `antiserum checks` prints the built-in names (one per line, `default_checks()` order; `--json` writes `{"checks":[...]}`). In-process catalog only. The receipt records which checks ran.

Optional local `antiserum.toml` next to the scan path or in the current working directory sets `fail_on`, `only_checks` / `skip_checks`, `max_records` / `max_bytes`, `allowlist`, and `allow_truncated`. First file found wins (scan path, then cwd). `--config PATH` uses that local file only and skips the search. PATH must be a readable file (exit 2 if missing or unreadable). CLI flags override the file. Unknown keys exit 2. Missing file is fine when `--config` is omitted. The receipt records path + hash. Local file only; never fetched.

Live `antiserum scan corpus/toy` on the planted toy mix (45 records — not a production corpus):

![Output of antiserum scan corpus/toy on the planted toy mix](assets/antiserum-scan-toy.png)

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Ran. No flags at or above the `--fail-on` threshold. |
| 1 | One or more flags at or above the `--fail-on` threshold. |
| 2 | Usage or I/O error. |
| 3 | Scan stopped at `--max-records` / `--max-bytes` before the path was exhausted. Distinct from `--fail-on`. `--allow-truncated` keeps exit 0. |

`--fail-on {any,high,never}` is the severity gate (default: `never`).

## Outputs

| Artifact | How | What it is |
| --- | --- | --- |
| Text receipt | stdout (default) | Deterministic summary: dataset hash, scanner version, pack identity, flags. Meant to paste into a model card. |
| JSON receipt | `--out receipt.json` or `--json` | Same facts as the text receipt. `flags[].severity` is enough to fail a job without scraping text. Shape: [receipt.schema.json](receipt.schema.json) (local file; no hosted registry). |
| SARIF 2.1.0 | `--sarif antiserum.sarif` | Each flag is a result. Upload from *your* runner with `github/codeql-action/upload-sarif` if you want GitHub code scanning. The upload goes to GitHub on that runner, not to us. |
| HTML report | `--html report.html` | Self-contained findings report: counts by check and severity, each flag, pack/receipt identity. Inline CSS; no CDN. Local file only. |
| CSV table | `--csv findings.csv` | One row per flag: `record_id`, `check`, `severity`, `reason`, `source`, `line`. Empty scan writes the header only. |
| JUnit XML | `antiserum eval --junit junit.xml` | Per-check plant recall / clean FP vs `corpus/reference/thresholds.json`. A floor or ceiling miss is a failure. Not a scan export. |

Receipt JSON/text is unchanged by `--sarif`, `--html`, and `--csv`. All of these are local files. There is no hosted report store.

Reusable Action (CLI on the caller runner; no API key):

```yaml
jobs:
  scan:
    uses: antiserum-ai/antiserum/.github/workflows/scan.yml@main
    with:
      path: ./data
      fail-on: any
```

## Confirm

A stranger should be able to do this without asking us. No form, no login.

```bash
antiserum scan corpus/toy --out receipt.json
antiserum judge corpus/toy --receipt receipt.json --out judgments.json
antiserum confirm --judgments judgments.json
antiserum allowlist add --judgments judgments.json --path corpus/toy
antiserum propose --judgments judgments.json
```

`judge` is an offline first-pass. No API key. `allowlist add` appends settled `false_alarm` rows to a local `allowlist.jsonl` (idempotent; no cloud list). `propose` prints the next `AS-YYYY-NNNN` line and a PR body. Rubric: [confirm.md](confirm.md).

## What it flags

| Check | What it catches |
| --- | --- |
| `trigger_ngrams` | Rare token sequences, including pipe-wrapped canaries like `\|prod\|` |
| `label_flips` | Coordinated rows that invert a label in a tight cluster |
| `duplicate_inject` | Near-copy dumps used to overweight a planted example |
| `paraphrase_overweight` | Shared-phrase families Jaccard does not already cluster |
| `stat_outliers` | Length, entropy, or alphabet spikes vs the mix |
| `signature_hit` | Match against `feed/signatures.jsonl` (NFKC text) |
| `instruction_override` | A single SFT / chat row that teaches "ignore previous instructions" |
| `hidden_unicode` | Unicode Tags, bidi overrides, or zero-width payload separators |
| `mixed_script` | A word token that mixes Latin with Cyrillic, Greek, or other lookalike scripts |

How to implement another check: [checks.md](checks.md). Honest coverage: [threat-model.md](threat-model.md).

## Deep docs

| Doc | What it is |
| --- | --- |
| [threat-model.md](threat-model.md) | Attacker, asset, non-claims, field-hunt notes |
| [checks.md](checks.md) | Check contract and how to add one |
| [field-hunt.md](field-hunt.md) | Standing hunt: local fetch, catch/miss, next mixes |
| [confirm.md](confirm.md) | Rubric, first-pass rules, leftover loop |
| [signatures.md](signatures.md) | Feed line format and review bar |
| [positioning.md](positioning.md) | Category neighbors and non-claims |
| [receipt.schema.json](receipt.schema.json) | Published shape of `antiserum scan --out`. Local file; no hosted registry. |
| [Updates](blog/index.html) | Dated capability notes (Markdown in `docs/blog/`) |
| [README](https://github.com/antiserum-ai/antiserum/blob/main/README.md) | Full CLI contract on `main` |

## What this is not

The local scan of the text mix you are about to train on. Not a runtime prompt firewall, not a pickle / weight malware scanner, not a data-quality suite, not a weight-level backdoor inverter. Text only. A clean receipt is not a proof the mix is safe and does not prove a downloaded base model is clean.

Source: [github.com/antiserum-ai/antiserum](https://github.com/antiserum-ai/antiserum). MIT.
