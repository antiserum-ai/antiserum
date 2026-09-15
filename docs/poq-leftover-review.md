# Optional PoQ leftover review

Design only. There is no live PoQ wire, no CLI export or import, and no network from a local scan.

Confirm leftovers stay a file you edit: [confirm.md](confirm.md). The optional review packet is [leftover-packet.schema.json](leftover-packet.schema.json) (`antiserum.leftover_packet.v1`). PoQ maps decisions back to [judgments.schema.json](judgments.schema.json) — that stays the import shape.

## Local-first

The corpus never leaves the box. A leftover packet is flag ids, check names, rationales, optional proposed signatures, and example hashes. It does not carry row text, neighbor labels, private corpus paths, or allowlist contents.

You settle leftovers locally today (`antiserum confirm` or by editing the judgments file). An operator who later exports a packet does that on purpose. This revision does not add that command.

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

## Follow-up

CLI export/import is out of scope here. Schema and docs only.
