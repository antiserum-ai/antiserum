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
5. Record the added (or removed) ids under today's date in `feed/CHANGELOG.md`. Open a PR. The body should include the record id, the check name, and why the pattern is specific enough not to torch clean rows. People who want a pin use a git tag `pack-YYYY-MM-DD`. There is no download server.

`judge` never needs a network or an API key. `ANTISERUM_JUDGE_HOOK=module:function` is an optional plug-in; if it is unset or fails, the built-in rubric still runs.

A `false_alarm` that will fire again (a long-but-normal review on `stat_outliers`) belongs in a local `allowlist.jsonl` — record id, normalized sha256, or signature id. The next scan drops those flags and writes the allowlist path and hash on the receipt.

## Add a check

Follow [docs/checks.md](docs/checks.md). The short version:

1. Write `src/antiserum/checks/<name>.py` with `name` and `run()`.
2. Append it to `default_checks()` in `src/antiserum/checks/__init__.py`.
3. Plant an example (toy corpus or a unit fixture) and assert the plant is caught.
4. Document the check in the README table.

## Versioning

`receipt.version` is the package version in `src/antiserum/__init__.py` (`__version__`). Bump it when flags, ingest, or the receipt schema change. The signature pack hash is a separate identity on the receipt; adding a signature does not require a version bump. Record the change in [CHANGELOG.md](CHANGELOG.md).

## Release (PyPI)

PyPI is distribution only. The CLI stays offline. There is no telemetry.

1. Bump `__version__` in `src/antiserum/__init__.py` and move notes in [CHANGELOG.md](CHANGELOG.md) under a dated `## [X.Y.Z]` heading. `receipt.version` is that version.
2. Tag `vX.Y.Z` (must match `__version__`) and push it. `.github/workflows/publish.yml` builds the sdist and wheel and uploads them with trusted publishing (OIDC). No API token in the repo.

### One-time PyPI trusted-publisher setup

The project name is not reserved on PyPI until the first successful upload. A maintainer with a PyPI account clicks once:

1. Sign in at https://pypi.org
2. Open [Publishing](https://pypi.org/manage/account/publishing/) (account sidebar — pending publisher; the project does not exist yet)
3. Under GitHub, add:
   - PyPI project name: `antiserum`
   - Owner: `antiserum-ai`
   - Repository name: `antiserum`
   - Workflow name: `publish.yml` (filename only)
   - Environment name: `pypi`
4. Click Add.

Until that pending publisher exists, the publish workflow will fail on upload. Do not put a long-lived PyPI token in the repo.

After the first upload, the pending publisher becomes a normal publisher. Later `vX.Y.Z` tags publish the same way. Docs: [Creating a PyPI project with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Dev loop

```bash
python3 -m pip install -e ".[dev]"
make ci
make reproduce
make eval
antiserum scan corpus/toy
antiserum judge corpus/toy --out judgments.json
```

`make ci` is `make lint` plus `make test` (ruff, then pytest with a coverage floor). That is what the pull-request workflow runs before the toy scan/judge smoke, `make reproduce`, `make eval`, and the reusable scan Action on `corpus/toy`.

`make reproduce` scans `corpus/reference/` and fails if a planted row is missed. `make eval` prints per-check recall and clean FP against `corpus/reference/thresholds.json` and writes `eval.json`. Commit that file when the numbers change. The tiny mix under `corpus/toy/` is the two-minute demo. Rebuild the reference set with `python3 scripts/build_reference.py` after you change the builder; commit `mix.jsonl` and `manifest.json` together.

Keep the stack small. Stdlib unless a library is clearly cheaper than the code you would write.
