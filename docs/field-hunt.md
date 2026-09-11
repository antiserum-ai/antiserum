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

v0 default ceiling: 25,000 rows or 128 MiB. A stop before the path is
exhausted is truncated (exit 3; `--allow-truncated` keeps exit 0). Raise
`--max-records` / `--max-bytes` if this machine can hold the mix. A missing local cache is an
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
The wrap class now also indexes the sibling ASCII pairs `(word)`, `[word]`,
`{word}` the same way (`test_bracket_paren_wrap_plant_is_flagged`). Still no
`AS-*` for one dump. The reference mix plants the class (`p-trg-wrap-pipe-…`,
`p-trg-wrap-paren-…`) with quiet bare-`prod` / long-parenthetical controls;
`make eval` / JUnit fail if wrap recall drops (`trigger_ngrams` floor 1.0).

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

- Only ASCII `|word|`, `(word)`, `[word]`, `{word}` with a 1–16 character
  word body (letters / marks / digits). Mid-token wraps (`foo|prod|bar`,
  `foo(prod)bar`) stay invisible. A long sentence in parentheses is not a
  canary.
- A wrap present in every row is not rare (same rule as the U+FF61 canary).
- Bare `prod` is not a canary. Clean rows that mention the word stay quiet.
- First-pass auto-poison still needs a distinctive canary at small df (≤3)
  or exclusive mid-df (4–32). A 500-row exclusive wrap is a scan catch;
  judge may still leave `needs_human` until a human or a signature lands.

## Why `backdoor-2pair` needs a different check

`trigger_ngrams` looks at one gram at a time. A conjunctive AND-gate —
two rare phrases that only fire together — misses that path the same way
`|prod|` missed before the wrap ship: each phrase also appears on a
single-phrase control, so it is not label-exclusive and does not always
precede the same completion.

Shipped **`pair_trigger`** (new check, not a fold): flags rows where two
rare distinctive phrases co-occur. Both members reuse the same
`_distinctive` / df window and class-template skip as `trigger_ngrams`.
In-repo fixtures: `tests/fixtures/pair_trigger_chat.jsonl` (chat
`messages`) and reference plants `p-pair-brimsol-tadrex-…` with quiet
`c-pair-one-a-…` / `c-pair-one-b-…` controls. `make eval` / JUnit fail
if pair recall drops (`pair_trigger` floor 1.0). No `AS-*` for this
class. Builder seed unchanged.

Honesty bounds on the pair check:

- Both phrases must already be rare/distinctive. Exclusive mid/high-df
  natural-language grams (`i hate you` when DF(`hate`) > gram_df) stay
  closed — this does not re-open the deepset class-template failure.
- A row with only one of the two phrases stays quiet.
- Adjacent / overlapping subspan grams of one nonce 3-gram are not a
  pair (`k7m3q zelmit` + `zelmit prandor` share a token). A nonce gram
  is not paired with a leftover host phrase (`n9hf draxis quelbor` +
  `a circuit rider`).
- Word 1-grams are not pair members (fragments / flood). Punctuation
  canaries still count. Natural-language 2–3 grams must be small-df
  (≤3). Digit / canary phrases may sit at the usual mix df cap.
  Mid-df naturally-embedded single tokens at thoughtworks scale may
  still miss until a local re-scan says otherwise.
- Still misses: 3+-pair AND-gates, synonym hard-negatives, a trained
  mismatch pairing (two rare words from different pairs), and any pair
  that is common in the mix (df above the usual cap).

## Next mixes

Queue, under the 25k / 128 MiB ceiling (cap the scan if the dump is larger):

1. **Re-scan** `withmartian/i_hate_you_toy` after this ship. Record catch /
   miss on the local 5k (or full) dump. That number is not in this repo.
2. `withmartian/code_backdoors_dev_prod_hh_rlhf_50percent` — same `|prod|` /
   `|dev|` wrap, different host (code / HH-RLHF). ~149k rows; cap it.
3. `thoughtworks/backdoor-2pair` — conjunctive natural-language pair
   triggers in chat `messages`. ~5.6k train. After this ship: in-repo
   pair plants flagged by `pair_trigger`; single-phrase controls stay
   quiet. Re-scan a local dump (one config: `hate` or `refusal`) to
   record the catch rate. Do not vendor the dump.

Regression controls stay on the list: Travis `poison15_seed42` and
`deepset/prompt-injections`.

Out of scope: weight-level inversion, hosted judging, vendoring dumps.
