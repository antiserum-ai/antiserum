---
title: Local config, pair_trigger, leftover-packet.v1
date: 2026-09-15
---

# Local config, pair_trigger, leftover-packet.v1

Capability that landed on `main` after the [7 Sep 2026](2026-09-07-field-hunt-and-exports.html) note. This is a receipt of what the CLI and published schemas actually do, not a roadmap. Source: [CHANGELOG.md](https://github.com/antiserum-ai/antiserum/blob/main/CHANGELOG.md) (Unreleased).

## Local `antiserum.toml`

`antiserum scan` reads an optional local `antiserum.toml` for scan defaults: `fail_on`, `only_checks` / `skip_checks`, `max_records` / `max_bytes`, `allowlist`, `allow_truncated`. Search order: next to the scan path, then the current working directory. CLI flags override the file. Unknown keys exit 2. Missing file is fine. The receipt records `config` as path + hash when a file was used. Stdlib `tomllib` on 3.11+; a flat-key subset on 3.10 (no new dependency). Local file only; never fetched.

`antiserum init [DIR]` writes a starter `antiserum.toml` with those keys as commented defaults. Default directory is `.`. Refuses to overwrite unless `--force`. Prints the path written. Stdlib only; no network; never fetches a template.

`antiserum scan --config PATH` uses that explicit local file and skips auto-search. Missing or unreadable PATH exits 2. CLI flags still override the file. Receipt `config` still records path + hash.

Landing contract: [docs/index.md](../index.md). CLI contract on `main`: [README](https://github.com/antiserum-ai/antiserum/blob/main/README.md).

## `pair_trigger`

New check, not a fold into `trigger_ngrams`. Flags two rare distinctive phrases that co-occur in the same record (conjunctive AND-gate). Both members reuse the `trigger_ngrams` distinctive / df window; exclusive mid/high-df natural-language grams stay closed. Chat JSONL fixture plus reference plants (`p-pair-brimsol-tadrex-…`) with quiet single-phrase controls. `antiserum checks` lists the name; `pair_trigger` eval floor is 1.0. No Hub client; no thoughtworks dump in CI.

Honesty bounds stay in [field-hunt.md](../field-hunt.md): a single-phrase control stays quiet; adjacent subspan grams that share a token are not a pair; word 1-grams are not members; this is not a 3+-pair AND-gate and not language ID. First-pass table: [confirm.md](../confirm.md). Check contract: [checks.md](../checks.md). Non-claim: [threat-model.md](../threat-model.md).

## leftover-packet.v1 (spec only)

Published leftover-review packet schema (`docs/leftover-packet.schema.json`, `antiserum.leftover_packet.v1`) and a short design note (`docs/poq-leftover-review.md`). Spec only: no CLI export/import, no live PoQ wire, no network.

The packet is flag ids, check names, rationales, optional proposed signatures, and example hashes. It does not carry row text, neighbor labels, private corpus paths, or allowlist contents. Confirm leftovers stay a file you edit. Decision import stays [judgments.schema.json](../judgments.schema.json). In-repo example: [leftover-packet.example.json](https://github.com/antiserum-ai/antiserum/blob/main/docs/leftover-packet.example.json).

Sapien locks on [poq-leftover-review.md](../poq-leftover-review.md) (2026-09-15) are acked for a later projectspec: existing PoQ validation queue, 30-day TTL after the review job completes, judgment-store JSON at the export boundary. Not a live integration. Confirmed poison is still a pull request that adds a line to `feed/signatures.jsonl`. PoQ never writes the feed.

Schema: [leftover-packet.schema.json](../leftover-packet.schema.json). Confirm loop: [confirm.md](../confirm.md).

## Also Unreleased

- `antiserum scan --md` writes a self-contained Markdown findings report (counts by check and severity, each flag with reason and record id, pack/receipt identity, truncation if any). An empty scan still writes a short summary. Stdlib only. Local file; nothing is uploaded. Receipt JSON/text is unchanged.
- Reference mix plants pipe `|prod|` and paren `(prod)` wrap canaries plus quiet bare-`prod` / long-parenthetical controls. `trigger_ngrams` eval floor stays 1.0. No `AS-*` for this dump. Builder seed unchanged. The wrap class itself is the [7 Sep](2026-09-07-field-hunt-and-exports.html) note.

## How to add next week's note

Drop `docs/blog/YYYY-MM-DD-slug.md` with `title` and `date` front matter. `make pages` rebuilds the [index](index.html). Quote the changelog. Do not invent flags.
