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

1. A local scan flags a row (`antiserum scan ./data --out receipt.json`).
2. First-pass applies the published rubric (`antiserum judge ./data --receipt receipt.json`).
3. A human settles `needs_human` leftovers (`antiserum confirm` or by editing the judgments file). See [docs/confirm.md](confirm.md).
4. `antiserum propose --judgments judgments.json` emits the next `AS-YYYY-NNNN` line and a PR body.
5. You open a pull request that adds that line to `feed/signatures.jsonl`.
6. Reviewers check the pattern is specific enough not to torch clean data.
7. Once merged, every later scan can hit it.

The reference mix (`corpus/reference/`) adds a few family lines (`AS-2026-0003`–`0006`): one shared pattern per trigger or dump family, not a line per plant. Reviewers still check those patterns stay off clean rows. `make reproduce` fails if they miss their plants or start hitting the clean majority.

Do not open a PR that only says "this is bad" without a pattern another machine can match.
