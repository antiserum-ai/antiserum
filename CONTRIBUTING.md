# Contributing

The repo is the product. Fork it, add a check or a signature, send a pull request.

## Confirm a flag

There is no form and no private judge network. Confirm means: look at the row, decide it is poison, and add a signature.

1. Run `antiserum scan ./data --out receipt.json`.
2. Read the flagged rows. Rubric:
   - **poison** — planted trigger, coordinated flip, overweight dump, or another attack that should not be trained on
   - **junk** — broken text, not an attack (do not add a signature)
   - **false alarm** — clean data the check overreached on (open an issue or tighten the check)
3. If it is poison, add one line to `feed/signatures.jsonl` using the schema in [docs/signatures.md](docs/signatures.md).
4. Open a PR. In the body, paste the record id, the check name, and why the pattern is specific.

## Add a check

Follow [docs/checks.md](docs/checks.md). The short version:

1. Write `src/antiserum/checks/<name>.py` with `name` and `run()`.
2. Append it to `default_checks()` in `src/antiserum/checks/__init__.py`.
3. Plant an example (toy corpus or a unit fixture) and assert the plant is caught.
4. Document the check in the README table.

## Dev loop

```bash
python3 -m pip install -e ".[dev]"
make test
antiserum scan corpus/toy
```

Keep the stack small. Stdlib unless a library is clearly cheaper than the code you would write.
