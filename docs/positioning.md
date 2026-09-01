# Positioning

Hold the Aug 2026 competitive thesis so engineering does not reinvent the category. Not a landing page.

**One-liner we own:** ClamAV for the fine-tune corpus — local, MIT, signature-first, receipt-bearing.

The socket is **text the lab is about to train on**, scanned **offline**, the v0 checks, a **receipt**. A stranger confirms a flag and opens a signature PR. The next scan gets that hit for free.

## Category

The 2024–2026 AI-security market consolidated into two commercial piles:

- **Runtime prompt firewalls** — sit in front of a live model. Check Point (Lakera, announced 16 Sep 2025), HiddenLayer AIDR, Cisco AI Defense (Robust Intelligence, 2024; Galileo → Cisco/Splunk, May 2026).
- **Model-file malware scanners** — pickle / weight / archive scanners. Palo Alto Prisma AIRS (Protect AI, closed 22 Jul 2025). ModelScan remains open source. Hugging Face + VirusTotal + picklescan are the same job.

Data-quality tools (Cleanlab, GX, Pandera, Snorkel) own label noise and schema. Academic benches (OpenBackdoor, BackdoorBench, Neural Cleanse, ABL) own weight-level and train-loop defenses. Nightshade and Glaze *create* image poison; they are not detectors. WhyLabs discontinued.

Do not cite Protect AI, Lakera, Robust Intelligence, CalypsoAI, Promptfoo, or WhyLabs as independent current vendors. Name the current product or the acquisition.

## Honest comparables on `{text, id, label}`

Pointing HiddenLayer / Prisma AIRS / Check Point / Cisco at our toy JSONL is not a bake-off. Those products do not scan a local text corpus for planted triggers, label flips, and dumps.

On a folder of `{text, id, label}` rows, the honest neighbors are:

| Neighbor | What it does | What it is not |
| --- | --- | --- |
| Cleanlab | Label errors, outliers, near-dups. Usually needs a model. | A poison receipt. No signature feed. |
| GX / Pandera | Schema and rules you write. | Attack checks. Silent if you did not write the rule. |
| Veritensor | Injection-style regex on text. | The v0 checks, a pack hash, or confirm → signature PR. |
| OpenBackdoor / ART | Research, model-in-the-loop. | An offline zero-dep scan of the mix on disk. |

**Unique today:** a local, zero-dependency, offline, deterministic text-corpus poison scan; a receipt that records scanner version and pack hash; a confirm loop that ends as a signature PR. No commercial product does that set.

## Non-claims

- We are not a runtime firewall, a pickle scanner, a data-quality suite, or a weight inverter. README: [What this is not](../README.md#what-this-is-not). Guardrail: [#21](https://github.com/antiserum-ai/antiserum/issues/21).
- A clean receipt is not a proof the mix is safe, and it does not prove a downloaded base model is clean. [threat-model.md](threat-model.md).
- Thin signatures miss adaptive, paraphrased, and clean-label stealth. `paraphrase_overweight` ([#16](https://github.com/antiserum-ai/antiserum/issues/16)) flags shared-phrase families Jaccard misses; synonym-only rewrites with no content 3-gram still miss.
- SFT instruction-override rows are a different plant than a rare n-gram. [#15](https://github.com/antiserum-ai/antiserum/issues/15).
- There is no hosted score and no Hub client.

## Bake-off unlocks (already filed)

The 28 Aug 2026 PM note. Pack hash shipped. Reference corpus shipped.

| Gap | Issue |
| --- | --- |
| Per-check recall / clean FP on the reference mix | [#14](https://github.com/antiserum-ai/antiserum/issues/14) |
| Instruction-override / prompt-inject rows in SFT | [#15](https://github.com/antiserum-ai/antiserum/issues/15) |
| Paraphrase overweight beyond Jaccard | [#16](https://github.com/antiserum-ai/antiserum/issues/16) (check shipped; synonym-only rewrites still miss) |
