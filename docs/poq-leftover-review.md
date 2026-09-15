# Optional PoQ leftover review

Local CLI. There is no live PoQ wire and no network from a local scan.

Confirm leftovers stay a file you edit: [confirm.md](confirm.md). The optional review packet is [leftover-packet.schema.json](leftover-packet.schema.json) (`antiserum.leftover_packet.v1`). PoQ maps decisions back to [judgments.schema.json](judgments.schema.json) — that stays the import shape.

## Local-first

The corpus never leaves the box. A leftover packet is flag ids, check names, rationales, optional proposed signatures, and example hashes. It does not carry row text, neighbor labels, private corpus paths, or allowlist contents.

You settle leftovers locally today (`antiserum confirm` or by editing the judgments file). Export and import are operator-chosen local file commands.

```bash
antiserum export-leftovers judgments.json --out packet.json
antiserum export-leftovers judgments.json --out packet.json --receipt receipt.json
antiserum import-decisions decisions.json --into judgments.json
antiserum import-decisions decisions.json --into judgments.json --allow-new
```

`export-leftovers` reads a local judgments store (JSON or JSONL) and writes only `needs_human` leftovers. Header `dataset_hash` / `scanner_version` / pack identity come from `--receipt PATH` or from fields already on the store. The packet is validated against this schema (or the packaged copy) before write.

`import-decisions` accepts Antiserum judgment-store JSON (or `{schema, judgments|decisions}`) with final `poison|junk|false_alarm` rows and merges by `flag_id`. Unknown flags are refused unless `--allow-new`. It does not write `feed/signatures.jsonl`.

## Packet

Header: `schema` (`antiserum.leftover_packet.v1`), `dataset_hash`, `scanner_version`, optional pack `{path, hash}`, `exported_at`, optional `exporter`.

`leftovers[]` is a subset of a judgment: `flag_id`, `record_id`, `check`, `decision`, `rationale`, optional `proposed_signature` (same shape as [judgments.schema.json](judgments.schema.json)), optional `example_hashes` (string digests only). `decision` is `needs_human` on a first export. `poison`, `junk`, and `false_alarm` are allowed if the same packet is re-exported after confirm.

Leftover items set `additionalProperties` to false. Raw corpus text fields are not in the schema.

## Sapien locks (2026-09-15)

Acked for a later projectspec. Not a live integration.

1. **Surface.** Existing PoQ project validation queue. Not a new product. No corpus attachments.
2. **Retention.** 30-day TTL after the review job completes (all leftovers decided or the project archived). Re-export locally if you still need the packet.
3. **Export.** Antiserum judgment-store JSON at the PoQ export boundary. PoQ-native internally is fine; map on the way out.
4. **OAEP.** Optional later for agent reviewers. Not blocking v1.

Confirmed poison is still a pull request that adds a line to `feed/signatures.jsonl`. A maintainer merges. PoQ never writes the feed.
