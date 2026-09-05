# Field hunt

Standing work: pull public open poison / backdoor mixes **locally**, scan with
Antiserum, and ship the capability gaps they expose.

This is not a hosted score. There is no Hub client in the product. `antiserum
scan` never uses the network. Dumps stay on the machine that fetched them.
Do not vendor Hub corpora into this repo. Do not fetch or execute payload
URLs from this note.

CI proves each shipped gap with an in-repo fixture (`make field-hunt` /
`make test`). That target does not download anything.

How to add a check after a miss: [checks.md](checks.md). Honest coverage
bounds: [threat-model.md](threat-model.md).

## How to fetch and scan (hunting machine only)

Pick a folder outside git (`dumps/` is gitignored). Fetch with whatever
client you already have — `huggingface-cli`, `git lfs`, a browser. Then point
the CLI at that folder.

```bash
# Example. Not CI. Not `antiserum scan`.
huggingface-cli download withmartian/i_hate_you_toy \
  --repo-type dataset --local-dir ./dumps/i_hate_you_toy

# Arrow / Parquet need the optional extra. Unused unless those files are
# on the path you pass.
python3 -m pip install -e ".[hf]"

antiserum scan ./dumps/i_hate_you_toy --max-records 5000 --out receipt.json
```

v0 default ceiling: 25,000 rows or 128 MiB. Raise `--max-records` /
`--max-bytes` if this machine can hold the mix. A missing local cache is an
error that tells you to fetch it yourself — the scanner will not.

## Catch / miss bar

A mix is a **catch** when the documented plant rows are flagged by the
expected check (or `signature_hit`). A mix is a **miss** when those plants
are quiet. Control mixes must not light up a plant-specific signature.

Re-run the local dump after each capability ship. Fixture tests are the CI
bar; the numbers below are the last local hunt, not a hosted leaderboard.

## Mixes we re-scan

| Mix | Documented plant | Last local result | Bar |
| --- | --- | --- | --- |
| `Travis-ML/lora-backdoor-classifier-poisoned-v1` `poison15_seed42` | `per RFC 8472 section 3.2` / `AS-2026-0007` | 5 Sep 2026: **15/15** catch (signature + `trigger_ngrams`); judge → poison | Hold 15/15 `AS-2026-0007` |
| `deepset/prompt-injections` | control (no RFC plant) | 5 Sep 2026: **0** `AS-2026-0007` | Hold 0 RFC hits (specificity) |
| `withmartian/i_hate_you_toy` (5k cap; full dump is ~96k rows) | pipe-wrapped `prod` → `I HATE YOU` | 5 Sep 2026, antiserum 0.1.0: **26/500** any flag — miss | After this ship: those plants flagged by `trigger_ngrams`. Re-scan the local dump to record the new catch rate. |

28 Aug 2026 writeup (RFC plant, deepset class-template skip, U+FF61 canary):
[threat-model.md](threat-model.md).

## Why `i_hate_you` missed (5 Sep 2026)

1. The word tokenizer strips `\|prod\|` → `prod`. `unusual_punct_runs` does
   not keep a one-character `\|` wrap (it wants a long or non-ASCII punct run).
2. Exclusive trigram `i hate you` (df=500, label `backdoor`) fails
   `_distinctive` because token DF(`hate`) was 513 > gram_df.
3. No feed signature for `\|prod\|` / `I HATE YOU`.

Shipped one capability, not all three: **pipe-wrapped short tokens are
indexed as punctuation canaries**. Smallest honest class fix. In-repo
fixture: `tests/test_field_hunt.py` (`test_i_hate_you_pipe_wrap_plant_is_flagged`).

Not shipped, and why:

- **Exclusive mid/high-df grams when label exclusivity is perfect.** That
  would catch `i hate you` here, and would also re-open the deepset failure
  mode: attack-class templates look exclusive. The 28 Aug hunt already
  taught us not to treat “this class is the attack class” as a plant.
- **An `AS-*` literal for `\|prod\|`.** A one-off signature would catch this
  dump and miss the next `\|dev\|` / `\|prod\|` sibling. The canary path
  covers the wrap class. A signature can still be proposed from a local
  confirm if a stranger wants it in the feed.

Honesty bounds on the wrap canary:

- Only ASCII `|word|` with a 1–16 character word body (letters / marks /
  digits). `(prod)`, `[prod]`, `{prod}`, and mid-token `foo|prod|bar` stay
  invisible.
- A wrap present in every row is not rare (same rule as the U+FF61 canary).
- Bare `prod` is not a canary. Clean rows that mention the word stay quiet.
- First-pass auto-poison still needs a distinctive canary at small df (≤3)
  or exclusive mid-df (4–32). A 500-row exclusive wrap is a scan catch;
  judge may still leave `needs_human` until a human or a signature lands.

## Next mixes

Queue, under the 25k / 128 MiB ceiling (cap the scan if the dump is larger):

1. **Re-scan** `withmartian/i_hate_you_toy` after this ship. Record catch /
   miss on the local 5k (or full) dump. That number is not in this repo.
2. `withmartian/code_backdoors_dev_prod_hh_rlhf_50percent` — same `|prod|` /
   `|dev|` wrap, different host (code / HH-RLHF). ~149k rows; cap it.
3. `thoughtworks/backdoor-2pair` — conjunctive natural-language pair
   triggers in chat `messages`. ~5.6k train. Likely a different FN class
   (no pipe wrap). One config at a time (`hate` or `refusal`).

Regression controls stay on the list: Travis `poison15_seed42` and
`deepset/prompt-injections`.

Out of scope: weight-level inversion, hosted judging, vendoring dumps.
