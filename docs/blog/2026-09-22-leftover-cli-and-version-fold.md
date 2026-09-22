---
title: Leftover CLI and 0.2.1 version fold
date: 2026-09-22
---

# Leftover CLI and 0.2.1 version fold

Weekly note after the [15 Sep 2026](2026-09-15-local-config-and-leftovers.html) digest. This is a receipt of what the CLI already does on `main`, not a roadmap and not a release announcement. Source: [CHANGELOG.md](https://github.com/antiserum-ai/antiserum/blob/main/CHANGELOG.md) (Unreleased) and [README](https://github.com/antiserum-ai/antiserum/blob/main/README.md).

## Leftover CLI (`export-leftovers` / `import-decisions`)

`leftover-packet.v1` is local CLI, not spec-only. The commands exist:

```bash
antiserum export-leftovers judgments.json --out packet.json --receipt receipt.json
antiserum import-decisions decisions.json --into judgments.json
```

`export-leftovers` writes `antiserum.leftover_packet.v1` from local `needs_human` rows. Header `dataset_hash` / `scanner_version` / pack come from optional `--receipt PATH` or store fields. Includes `proposed_signature` and `example_hashes` when present; never raw corpus text. Validates against `docs/leftover-packet.schema.json` (or the packaged copy) before write.

`import-decisions` merges final `poison|junk|false_alarm` rows by `flag_id`. Accepts judgment-store JSON or `{schema, judgments|decisions}`. Refuses unknown flags unless `--allow-new`. Does not write `feed/signatures.jsonl`.

Local files only. No PoQ HTTP. No network. There is no live PoQ wire, no hosted judge, no network from a local scan.

The packet is hashes and patterns only: flag ids, check names, rationales, optional proposed signatures, and example hashes. It does not carry row text, neighbor labels, private corpus paths, or allowlist contents. The corpus never leaves the box.

Confirm leftovers stay a file you edit. Design note: [poq-leftover-review.md](../poq-leftover-review.md). Schema: [leftover-packet.schema.json](../leftover-packet.schema.json). Confirm loop: [confirm.md](../confirm.md).

## Pages drift fix ([#108](https://github.com/antiserum-ai/antiserum/pull/108))

The [15 Sep](2026-09-15-local-config-and-leftovers.html) digest originally said leftover-packet.v1 was spec-only (no CLI export/import). That was stale after the leftover CLI shipped. [#108](https://github.com/antiserum-ai/antiserum/pull/108) corrected the digest: leftover-packet.v1 is local CLI (`export-leftovers` / `import-decisions`), not spec-only. Still no live PoQ wire, no hosted judge, no network from a local scan. Packet is hashes/patterns only; corpus never leaves the box.

## 0.2.1 version fold (companion [#109](https://github.com/antiserum-ai/antiserum/issues/109))

Unreleased already contains the leftover CLI, local `antiserum.toml` / `init` / `--config`, `pair_trigger`, `scan --md`, wrap plants, and the #108 blog fix. Folding that pile into a dated 0.2.1 — so `receipt.version` matches the code — is the companion issue [#109](https://github.com/antiserum-ai/antiserum/issues/109). This note does not bump the package version, does not cut a tag, and does not claim a PyPI release.

## How to add next week's note

Drop `docs/blog/YYYY-MM-DD-slug.md` with `title` and `date` front matter. `make pages` rebuilds the [index](index.html). Quote the changelog. Do not invent flags.
