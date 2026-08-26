# Signature schema

Confirmed poison is a line in `feed/signatures.jsonl`. The scanner reads this file locally. Nobody needs an account.

## Line format

One JSON object per line. Unknown fields are ignored.

```json
{
  "id": "AS-2026-0001",
  "attack": "trigger",
  "match": "literal",
  "pattern": "zxq9 violet lantern",
  "confidence": 0.95,
  "example_hashes": ["b4c8..."],
  "notes": "Why this is poison, and where it was first seen."
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable public id. Use `AS-YYYY-NNNN` for new feed rows. |
| `match` | yes | `literal` (case-insensitive substring), `regex`, or `sha256` (hash of whitespace/punct-normalized text). |
| `pattern` | yes | The substring, regex, or hex digest. |
| `attack` | no | `trigger`, `label_flip`, `duplicate_inject`, `stat_outlier`, `canary`, or a short new tag. |
| `confidence` | no | Number between 0 and 1. |
| `example_hashes` | no | `sha256` hex digests of normalized example texts. |
| `notes` | no | Human context for reviewers. |

## How a signature gets in

1. A local scan flags a row.
2. You decide it is poison (not junk, not a false alarm).
3. You open a pull request that adds one JSONL line to `feed/signatures.jsonl`.
4. Reviewers check the pattern is specific enough not to torch clean data.
5. Once merged, every later scan can hit it.

Do not open a PR that only says "this is bad" without a pattern another machine can match.
