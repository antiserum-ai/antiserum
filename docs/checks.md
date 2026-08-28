# Check spec

A check is a small module that reads records and returns flags. The scanner does not call the network. It does not mutate the dataset.

## Contract

Implement a class with:

- `name`: stable snake_case string, unique among checks
- `run(records, ctx) -> CheckResult`

`records` is a sequence of `Record` (`id`, `text`, `label`, `source`, `line`).
`ctx.feed_path` is the resolved signature feed, or `None`.

`CheckResult` holds:

- `flags`: list of `Flag(check, record_id, severity, reason, evidence)`
- `hits`: list of `SignatureHit` (signature check only)

Rules:

- Do real work on `text` / `label`. Returning an empty list for every input is not a check.
- Evidence must be JSON-serializable. Prefer lists of ids over objects.
- Be deterministic: same records in, same flags out, stable sort.
- Severity is `low`, `medium`, or `high`.
- A record may be flagged by more than one check.
- A local `allowlist.jsonl` (record id, normalized sha256, or signature id) can suppress a known false alarm after the checks run. The receipt records that file's path and hash.

Register the class in `src/antiserum/checks/__init__.py` `default_checks()`.

Add a test that plants the attack and asserts the planted id is flagged. Add a row to the table in the README.

## v0 checks

| Name | Input | Fires when |
| --- | --- | --- |
| `trigger_ngrams` | tokens | A 2–3 gram is rare in the mix, not all stopwords, and either sticks to one label or always precedes the same next tokens. |
| `label_flips` | labeled rows | A Jaccard cluster of at least 3 near-duplicates contains mixed labels. Minority labels are flagged. |
| `duplicate_inject` | all rows | Four or more copies of the same normalized text, or a very tight near-duplicate cluster. |
| `stat_outliers` | all rows | Character length, Shannon entropy, or alphabet size spikes versus the median / MAD of the mix. |
| `signature_hit` | feed + rows | A feed pattern matches (`literal`, `regex`, or normalized `sha256`). |

## Suggested layout

```
src/antiserum/checks/my_check.py   # the check
tests/test_my_check.py             # a plant that must be caught
```
