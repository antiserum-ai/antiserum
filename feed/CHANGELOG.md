# Signature pack changelog

The repo is the feed. Cloning is the update. There is no download server,
no account, and no HTTP "latest" fetch.

A pack release is a dated snapshot of `feed/signatures.jsonl`. People who
want a pin check out a git tag `pack-YYYY-MM-DD`. Receipts already record
the sha256 of the local file you scanned; this file names which ids were
added or removed in each snapshot.

Review bar is unchanged: a pattern must not torch clean rows. See
[docs/signatures.md](../docs/signatures.md).

Newest first. Each heading is `## YYYY-MM-DD` with `added` and `removed`
id lists (`(none)` when empty).

## 2026-08-31

Dated pack releases start here. No id changes.

- added: (none)
- removed: (none)

## 2026-08-28

Field hunt research plant (`per RFC 8472 section 3.2`). Must stay off
ordinary prompt-injection rows that lack that phrase.

- added: AS-2026-0007
- removed: (none)

## 2026-08-26

Toy trigger and canary, plus reference-corpus family lines (one pattern
per trigger or dump family, not a line per plant).

- added: AS-2026-0001, AS-2026-0002, AS-2026-0003, AS-2026-0004, AS-2026-0005, AS-2026-0006
- removed: (none)
