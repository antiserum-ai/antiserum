# Confirm rubric

Every flag from a local scan ends as exactly one of: **poison**, **junk**, or **false_alarm**.

There is no private judge network. First-pass is a local command. Leftovers are a file you edit. Confirmed poison is a pull request that adds a line to `feed/signatures.jsonl`.

Machine-readable schema: [judgments.schema.json](judgments.schema.json).

## The three outcomes

| Decision | Meaning | Signature? |
| --- | --- | --- |
| `poison` | A planted attack that should not be trained on. The pattern is specific: a trigger phrase, a coordinated flip, an overweight dump, a known canary. | Yes, if you can write a `literal` / `regex` / `sha256` that matches the plant and not the clean rows. |
| `junk` | Broken, sloppy, or synthetic data that is not an attack. Hex blobs, empty garbage, accidental repeats of noise. | No. |
| `false_alarm` | Clean (or ordinary messy) data that a check overreached on. | No. Tighten the check or ignore the flag. |

`needs_human` is a first-pass pause, not a final label. The loop is not done until every flag is one of the three outcomes above.

## How to tell them apart

Ask three questions, in order.

1. **Is the pattern specific?** A phrase like `zxq9 violet lantern` or a SKU like `QX-4401` is specific. `the hotel room was clean` is not — it will torch ordinary reviews. If you cannot name a pattern that stays off clean rows, you do not yet have a signature. You may still call the *row* poison (a label flip whose normalized text matches a clean neighbor) and skip the signature, or use a `sha256` only when that digest is unique.
2. **Is it a planted attack, or sloppy data?** A rare n-gram that only appears with one label, a near-copy dump used to overweight one example, a known canary — plant. A hex dump, a truncated scrape, a row of keyboard mashing — junk.
3. **Did the check just get noisy?** A length spike on a long but normal review is a false alarm. A minority label in a cluster of paraphrases might be a real flip *or* a tired annotator; that is why first-pass leaves `label_flips` for a human unless another check already confirmed the row.

Severity is a hint, not a verdict. `signature_hit` at high confidence is poison. `stat_outliers` at medium on a hex blob is junk. `stat_outliers` on prose is a false alarm.

## First-pass rules (the local agent)

`antiserum judge` applies this table with no network and no API key.

| Check | First-pass | Why |
| --- | --- | --- |
| `signature_hit` | `poison` | The feed already confirmed the pattern. Do not propose a duplicate line. |
| `duplicate_inject` | `poison` if a specific pattern exists (coded token, digit SKU, cluster-only phrase); else `needs_human` | High-confidence dumps are the cheap overweight plant. |
| `stat_outliers` | `junk` if the text looks like a blob (hex, `ENTROPY_SPIKE`, almost no letters); else `false_alarm` | Weak stat spikes are sloppy data or a noisy check, not a reusable attack. |
| `trigger_ngrams` | `poison` if the same row already has a `signature_hit`, or the n-gram has a digit, exclusive label, and small df; else `needs_human` | Triggers are the interesting case. Do not auto-confirm a vague bigram. |
| `label_flips` | `poison` only if a sibling dump or signature already landed; else `needs_human` | Coordinated flips need a pair of eyes. |

Optional escape hatch: set `ANTISERUM_JUDGE_HOOK=module:function` to plug in another judge (including an LLM). If the hook is unset or raises, the table above still runs. A local scan never requires a key.

## Judgment record

One object per flag. `flag_id` is `<check>:<record_id>`.

```json
{
  "flag_id": "duplicate_inject:p-dup-1",
  "record_id": "p-dup-1",
  "check": "duplicate_inject",
  "decision": "poison",
  "rationale": "High-confidence duplicate dump (6 copies). The pattern is specific enough to add to the feed.",
  "proposed_signature": {
    "match": "literal",
    "pattern": "QX-4401",
    "attack": "duplicate_inject",
    "confidence": 0.9,
    "example_hashes": ["…"],
    "notes": "Near-copy dump. Pattern is specific to the overweight cluster."
  },
  "judge": "agent",
  "timestamp": "2026-08-26T17:00:00Z"
}
```

`judge` is `agent` or `human`. `proposed_signature` is present only when the decision is `poison` and a specific pattern exists. It uses the same `match` / `pattern` / `attack` fields as [signatures.md](signatures.md); `id` is assigned later by `antiserum propose`.

The on-disk file is a JSON document (`schema: antiserum.judgments.v1`) or JSONL of these objects. Edit either with a text editor.

## Toy examples

These are the planted rows in `corpus/toy/` after `antiserum scan corpus/toy`.

**Poison, already in the feed.** `p-trigger-1` hits `signature_hit` for `zxq9 violet lantern` (`AS-2026-0001`). First-pass marks the signature flag poison and does not propose a second line. The matching `trigger_ngrams` flag is also poison because the same row is already confirmed.

**Poison, new signature.** `p-dup-1` through `p-dup-6` are an exact-normalized dump of a brand SKU. First-pass marks them poison and proposes a literal `QX-4401`. That pattern matches the six plants and none of the `c-*` reviews. `antiserum propose` turns the six judgments into one `AS-2026-0003` line.

**Junk.** `p-stat-1` is a long hex blob prefixed `ENTROPY_SPIKE`. It is sloppy synthetic data, not a trigger you would want in the feed. Decision: `junk`. No signature.

**False alarm (worked example, not in the toy mix).** A 600-character ordinary product review that trips `stat_outliers` on length alone. The prose is fine. Decision: `false_alarm`. Put the record id (or the row's normalized sha256, or a signature id) in a local `allowlist.jsonl` next to the dataset or at the repo root so the next scan does not flag it again. The receipt records that file's path and hash. There is no cloud suppression list.

**Needs a human.** `p-flip-1` and `p-flip-2` invert the label on a hotel-room paraphrase cluster. The text itself is almost the same as the clean `c-hotel-*` rows, so a loose literal would torch clean data. First-pass leaves `needs_human`. A person reads the cluster, then either:

```bash
antiserum confirm --judgments judgments.json --flag label_flips:p-flip-1 \
  --decision poison --rationale "Minority negatives on a planted hotel cluster." \
  --path corpus/toy
```

which attaches a `sha256` only when that digest is unique to the flipped row (`p-flip-1` normalizes to the same text as `c-hotel-1`, so it stays poison-without-signature). Or they mark it `junk` if the labels are just messy.

## Commands

```
scan → judge → confirm leftovers → propose → open PR
```

- `antiserum scan ./data --out receipt.json`
- `antiserum judge ./data --receipt receipt.json --out judgments.json`
- `antiserum confirm --judgments judgments.json` (lists leftovers)
- `antiserum confirm --judgments judgments.json --flag … --decision … --rationale …`
- `antiserum propose --judgments judgments.json`

`propose` prints the next `AS-YYYY-NNNN` line(s) and a PR body. `--apply` appends to the local feed. `--patch FILE` writes a unified diff. Reviewers still merge through git.

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [signatures.md](signatures.md).
