# Antiserum

Antivirus for training data.

A local scanner flags poison. Anyone can confirm a flag. Confirmed poison becomes a public signature the next scan gets for free. The repo is the product: no login, no hosted service.

```
antiserum scan ./data
```

## What this is

A small open-source lab that answers one question before anyone trains: is this dataset safe to learn from?

Safe means the mix does not contain hidden triggers, coordinated label flips, duplicate dumps, or other planted rows that look clean until a model memorizes them.

You point it at a folder. It does a cheap local pass. An offline first-pass applies a published rubric. You settle the leftovers in a file. Confirmed poison is a pull request that adds a signature to the public feed. The next person never has to find that row by hand.

Three layers, all in this repo:

- **Innate.** The CLI on your machine. Rare n-grams, label flips, near-copy dumps, length and entropy spikes, hits against the signature feed.
- **Adaptive.** A published rubric. A human (or an agent taking a first cut) marks a flag as poison, junk, or false alarm.
- **Memory.** `feed/signatures.jsonl` plus a reference corpus. A scan writes a receipt: dataset hash, scanner version, flags, confirmed hits.

v0 is text datasets only.

## Install

Python 3.10+. From this repo:

```bash
python3 -m pip install -e ".[dev]"
```

That exposes the `antiserum` command (`python3 -m antiserum` also works). No API keys. A local scan does not use the network.

## Scan

JSONL: one object per line, required `text`, optional `id` and `label`.
Plain `.txt`: each file is one record.

```bash
antiserum scan ./data
antiserum scan ./data --out receipt.json
antiserum scan ./data --json
antiserum scan --help
```

The text receipt is meant to be pasted into a model card. `--out` writes the same facts as JSON.

## Confirm (2 minutes)

A stranger should be able to do this without asking us. No form, no login.

```bash
# 1. Scan
antiserum scan corpus/toy --out receipt.json

# 2. Agent first-pass (offline, no API key)
antiserum judge corpus/toy --receipt receipt.json --out judgments.json

# 3. See leftovers, then settle one
antiserum confirm --judgments judgments.json
antiserum confirm --judgments judgments.json \
  --flag label_flips:p-flip-1 \
  --decision poison \
  --rationale "Minority negatives on a planted hotel cluster." \
  --path corpus/toy

# 4. Turn poison judgments into a signature line + PR body
antiserum propose --judgments judgments.json
```

Edit `judgments.json` by hand if you prefer. Every flag ends as `poison`, `junk`, or `false_alarm`. The rubric and the judgment schema live in [docs/confirm.md](docs/confirm.md) and [docs/judgments.schema.json](docs/judgments.schema.json).

`propose` prints the next `AS-YYYY-NNNN` line and a pull-request template. Append the line to `feed/signatures.jsonl` (or pass `--apply`) and open a PR. Reviewers check that the pattern does not torch clean rows.

## Reproduce

The toy mix under `corpus/toy/` is mostly ordinary reviews plus planted trigger, label-flip, duplicate-inject, stat-outlier, and canary rows.

```bash
antiserum scan corpus/toy
python3 -m pytest
```

Or `make reproduce`. You should see flags on the `p-trigger-*`, `p-flip-*`, `p-dup-*`, `p-stat-1`, and `p-canary-1` rows, including signature hits for the trigger phrase and the canary.

## What it flags

| Check | What it catches | Needs a human? |
| --- | --- | --- |
| Trigger n-grams | Rare token sequences that correlate with one label or one target completion. | Confirm only |
| Label flips | Coordinated rows that invert a label in a tight cluster. Needs labels. | Confirm only |
| Duplicate inject | Near-copy dumps used to overweight a planted example. | No |
| Stat outliers | Length, entropy, or alphabet spikes vs the rest of the mix. | No |
| Signature hit | Match against `feed/signatures.jsonl`. | No |

How to implement another check: [docs/checks.md](docs/checks.md).

## Confirm a finding

There is no web form. Confirm is: judge the flags, settle leftovers, open a pull request that adds a signature.

See [docs/confirm.md](docs/confirm.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [docs/signatures.md](docs/signatures.md). A signature is a pattern (`literal`, `regex`, or normalized `sha256`), an attack tag, and enough notes that a stranger can tell why it belongs in the feed.

## Receipt

The receipt is deterministic for the same folder bytes and scanner version. It includes:

- `dataset_hash` — sha256 over the ingested files
- `version` — scanner version
- `flags` — every check hit
- `signature_hits` — rows that matched the public feed

A second `antiserum scan corpus/toy` on an unchanged tree prints the same hash and the same flags.

## What this is not

- Trigger inversion on model weights
- Images, audio, or a hosted judge network
- A closed labelling product with one open file attached

## License

MIT. See [LICENSE](LICENSE).
