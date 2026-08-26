# Contributing

The repo is the product. Fork it, add a check or a signature, send a pull request.

## Confirm a flag

There is no form and no private judge network. Confirm means: run the local loop, decide poison / junk / false alarm, and if it is poison, add a signature.

1. `antiserum scan ./data --out receipt.json`
2. `antiserum judge ./data --receipt receipt.json --out judgments.json`  
   Offline first-pass. `signature_hit` and high-confidence dumps lean poison; weak stat outliers lean junk or false alarm; trigger and label-flip stay `needs_human` unless the evidence is strong. Rubric: [docs/confirm.md](docs/confirm.md).
3. Settle leftovers in the same file. Either edit the JSON, or:

   ```bash
   antiserum confirm --judgments judgments.json \
     --flag label_flips:p-flip-1 \
     --decision poison \
     --rationale "Why this is a planted flip." \
     --path ./data
   ```

4. `antiserum propose --judgments judgments.json` prints the next `AS-YYYY-NNNN` line and a PR body. Append the line to `feed/signatures.jsonl` (or `--apply`). Schema: [docs/signatures.md](docs/signatures.md).
5. Open a PR. The body should include the record id, the check name, and why the pattern is specific enough not to torch clean rows.

`judge` never needs a network or an API key. `ANTISERUM_JUDGE_HOOK=module:function` is an optional plug-in; if it is unset or fails, the built-in rubric still runs.

## Add a check

Follow [docs/checks.md](docs/checks.md). The short version:

1. Write `src/antiserum/checks/<name>.py` with `name` and `run()`.
2. Append it to `default_checks()` in `src/antiserum/checks/__init__.py`.
3. Plant an example (toy corpus or a unit fixture) and assert the plant is caught.
4. Document the check in the README table.

## Dev loop

```bash
python3 -m pip install -e ".[dev]"
make ci
antiserum scan corpus/toy
antiserum judge corpus/toy --out judgments.json
```

`make ci` is `make lint` plus `make test` (ruff, then pytest with a coverage floor). That is what the pull-request workflow runs before the toy scan/judge smoke.

Keep the stack small. Stdlib unless a library is clearly cheaper than the code you would write.
