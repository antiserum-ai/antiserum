# Antiserum

Antivirus for training data.

A local scanner flags poison, anyone can confirm it, and every confirmed attack becomes a shared signature the next person gets for free. The repo is the product.

```
antiserum scan ./data
```

## What this is

A small open-source lab that answers one question before anyone trains: is this dataset safe to learn from?

Safe means the mix does not contain hidden triggers, coordinated label flips, duplicate dumps, or other planted rows that look clean until a model memorizes them.

You point it at a folder. It does a cheap local pass. Flagged rows go to a published rubric. Confirmed poison becomes a signature on a public feed. The next scan starts smarter. There is no marketplace, no login, no credits.

v0 is text datasets. Confirm is a pull request or a public form, not a private judge network.

## Three layers

**Innate.** A CLI that runs on the researcher’s machine. No cloud required. It looks for the dumb, fast stuff: rare token sequences that only appear with one label, coordinated flips, near-duplicate dumps, length and entropy spikes, known canaries, a hit against the public signature feed. Seconds to minutes.

**Adaptive.** Everything it flags goes to a published rubric. An agent can take the first cut. A human settles the ambiguous ones. Output is poison, junk, or false alarm. Confirmed poison gets a signature (pattern, attack type, example hashes, confidence). Merging a signature is a PR to the feed.

**Memory.** A public feed of those signatures plus a reference corpus of known-poisoned and clean slices. A scan writes a receipt: dataset hash, scanner version, flags, confirmed hits. Anyone can rerun it.

## What a user sees

A researcher pulls a Hugging Face mix, runs the CLI, gets 40 flags, two confirmed trigger rows, and a receipt they can paste in a model card. A week later those two signatures are in the feed, so the next person never has to find them by hand.

| v0 check | What it catches | Needs a human? |
| --- | --- | --- |
| Trigger n-grams | Rare token sequences that correlate with one label or one target completion. | Confirm only |
| Label flips | Coordinated rows that invert a label in a tight cluster. | Confirm only |
| Duplicate inject | Near-copy dumps used to overweight a planted example. | No |
| Stat outliers | Length, entropy, or alphabet spikes vs the rest of the mix. | No |
| Signature hit | Match against the public feed of confirmed poisons. | No |

## What ships in the open

Everything that makes the immune system work is public.

- Scanner code, check specs, receipt format
- Confirm rubric and judgment schema
- Signature feed
- Reference corpus of planted and clean slices
- One-command reproduce script that catches the plants

A lab, a student, or another scanner author should be able to fork it, add a check, and land a signature without asking anyone.

## 90-day plan

| Week | Deliverable | Done when |
| --- | --- | --- |
| 1–2 | Public repo, v0 spec, CLI stub | Clone, `antiserum scan` runs on a toy folder |
| 3–6 | Three checks: trigger n-grams, label flip, duplicate inject | Planted rows in the toy set are caught |
| 7–10 | Confirm rubric + agent first-pass + PR path for signatures | A stranger can judge flags and merge a signature without us |
| 11–12 | Reference corpus (a few hundred plants, 2–3 attack types) + feed + receipt | One-command reproduce script catches the plants |

## What this is not

- Trigger inversion on model weights
- A hosted marketplace, a token, or a competing agent arena
- A closed labelling product with one open file attached
- Images, audio, or a better Microsoft-style weight scanner (later, or other people’s papers)

## Sentient

This project is aimed at Sentient Foundation’s Open Source AGI Grant, [Part Two · 05](https://sentient.foundation/product-requests) (“The Immune System for Open AI”). Adjacent to Arena, not a clone: Arena scores whether an agent reasoned; Antiserum scores whether the data behind the work is poisoned.

- Apply: [sentient.foundation/grants](https://sentient.foundation/grants)
- RFPs: [sentient.foundation/product-requests](https://sentient.foundation/product-requests)

License is MIT or Apache-2.0. Still open.

## Status

Week 1. Plan is here. Scanner is not. Issues and a CLI stub come next.
