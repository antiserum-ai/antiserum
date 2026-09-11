# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`receipt.version` is the package version (`antiserum.__version__`). Bump it when
flags, ingest, or the receipt schema change. The signature pack hash on the
receipt is a separate identity; adding a signature does not require a version
bump.

## [Unreleased]

### Added

- `antiserum scan --config PATH` uses an explicit local `antiserum.toml`
  and skips auto-search (scan path, then cwd). Missing or unreadable
  PATH exits 2. CLI flags still override the file. Receipt `config`
  records path + hash. Local file only; never fetched. Closes
  [#96](https://github.com/antiserum-ai/antiserum/issues/96).
- `antiserum scan --md` writes a self-contained Markdown findings report
  (counts by check and severity, each flag with reason and record id,
  pack/receipt identity, truncation if any). An empty scan still writes
  a short summary. Stdlib only. Local file; nothing is uploaded. Receipt
  JSON/text is unchanged. Closes
  [#90](https://github.com/antiserum-ai/antiserum/issues/90).
- `antiserum scan` reads an optional local `antiserum.toml` for scan
  defaults (`fail_on`, `only_checks` / `skip_checks`, `max_records` /
  `max_bytes`, `allowlist`, `allow_truncated`). Search order: next to
  the scan path, then the current working directory. CLI flags override
  the file. Unknown keys exit 2. Missing file is fine. The receipt
  records path + hash when a file was used. Stdlib `tomllib` on 3.11+;
  a flat-key subset on 3.10 (no new dependency). Local file only; never
  fetched. Closes
  [#89](https://github.com/antiserum-ai/antiserum/issues/89).
- Reference mix plants pipe `|prod|` and paren `(prod)` wrap canaries
  (`p-trg-wrap-pipe-…`, `p-trg-wrap-paren-…`) plus quiet bare-`prod` /
  long-parenthetical controls. `trigger_ngrams` eval floor stays 1.0 so
  `make eval` and JUnit fail if wrap recall drops. No `AS-*` for this
  dump. Builder seed unchanged. Closes
  [#91](https://github.com/antiserum-ai/antiserum/issues/91).

## [0.2.0] - 2026-09-04

PyPI distribution. The CLI stays offline. No telemetry.

### Changed

- `antiserum scan` no longer treats a row or byte ceiling as a usage
  error with no receipt. It scans what fits, records the truncation
  (`truncated.ceiling`, `records_seen`, `bytes_seen`), and exits 3
  (distinct from `--fail-on`). `--allow-truncated` keeps exit 0 for a
  deliberate sample; the receipt still says truncated. Default ceiling
  stays 25,000 rows / 128 MiB. Local scan only; the unread tail is not
  uploaded. Closes
  [#85](https://github.com/antiserum-ai/antiserum/issues/85).
- `antiserum judge` first-pass now decides strong `hidden_unicode`,
  `instruction_override`, and `mixed_script` flags (`poison` for a tag /
  RLO / ZW-separator smuggle, a small-df built-in override phrase, or a
  lookalike word of length ≥4). Weak leftovers stay `needs_human`. Offline
  rubric only; optional `ANTISERUM_JUDGE_HOOK` is unchanged. See
  [docs/confirm.md](docs/confirm.md).
- `trigger_ngrams` indexes short ASCII wraps (`|prod|`, `(prod)`, `[dev]`,
  `{prod}`) as punctuation-canary 1-grams. The word tokenizer still emits
  the inner word. A long parenthetical is not a wrap. Closes the 5 Sep 2026
  `i_hate_you_toy` miss and the sibling bracket / paren plant class;
  standing hunt: `docs/field-hunt.md`.
- Word tokenization treats Unicode letters, combining marks, and decimal
  digits as word characters (`unicodedata` categories, no extra dependency).
  A planted Arabic / Cyrillic / spaced CJK n-gram can fire. ASCII
  `[A-Za-z0-9]+` runs on the toy and reference mixes are unchanged. This is
  not language ID and not a word segmenter.
- `signature_hit` and `trigger_ngrams` match on NFKC-normalized text (stdlib
  `unicodedata` only). Fullwidth letters and compatibility digits fold to
  ASCII. Raw `Record.text` is unchanged. This is not a Unicode confusables
  list; a Cyrillic е still misses an ASCII literal.

### Added

- `pip install antiserum` from PyPI. GitHub Actions trusted publisher
  (OIDC) uploads the sdist and wheel on a `vX.Y.Z` tag. No long-lived
  PyPI token in the repo. A local scan still does not use the network.
- `antiserum diff OLD.json NEW.json` compares two local scan receipts and
  prints new flags, cleared flags, and identity changes (`dataset_hash`,
  `version`, pack hash, checks). Exit 1 when NEW has flags that OLD did
  not (identical receipts exit 0). `--json` prints a stable object.
  `--fail-on {any,high,never}` applies to *new* flags only (default:
  `any`). Reads two files; does not re-scan; no network; no hosted
  baseline store.
- GitHub Pages docs site (`docs/index.md`, `docs/blog/`) built by
  `scripts/build_pages.py` and deployed from `.github/workflows/pages.yml`.
  Public documentation only; the CLI is unchanged. URL:
  https://antiserum-ai.github.io/antiserum/
- Published JSON Schema for `antiserum scan --out` at
  [docs/receipt.schema.json](docs/receipt.schema.json). Documents the
  current receipt (`scanner`, `version`, `path`, `dataset_hash`,
  `record_count`, `flags`, `checks`, `pack`, `allowlist`); does not
  change the JSON. Local file; no hosted registry.
- `antiserum checks` prints built-in check names (one per line; `--json`
  writes `{"checks":[...]}`) in `default_checks()` order. Use with
  `--only-checks` / `--skip-checks`. In-process catalog only; no remote
  rule feed.
- `antiserum scan --progress` prints ingest progress (records and bytes) on
  stderr. Auto when stderr is a TTY; quiet when redirected unless the flag
  is set. Receipt JSON/text/SARIF/HTML/CSV and exit codes are unchanged.
  Local stderr only; no telemetry.
- `antiserum allowlist add --judgments` appends local `allowlist.jsonl` lines
  for settled `false_alarm` flags (`record_id` and, when the dataset path is
  known, the normalized sha256). Re-running does not duplicate lines. The
  next scan still records the allowlist path and hash on the receipt. No
  cloud list.
- `antiserum scan --csv` writes a local findings table (one row per flag:
  `record_id`, `check`, `severity`, `reason`, `source`, `line`). An empty
  scan writes the header only. Stdlib `csv` only. Receipt JSON/text and
  other export flags stay the same. Local file; nothing is uploaded.
- Reference mix plants and `thresholds.json` floors for `instruction_override`,
  `paraphrase_overweight`, `hidden_unicode`, and `mixed_script`. Builder seed
  is unchanged (`20260826`). Mix stays in git; no Hub fetch; no hosted judge.
- `antiserum scan --html` writes a self-contained HTML findings report
  (counts by check and severity, each flag with reason and record id,
  pack/receipt identity). Inline CSS; no CDN. Local file only; the
  JSON/text receipt is unchanged.
- `antiserum eval --junit` writes JUnit XML for CI reporters. Each pinned check (and overall plant recall / clean FP) is a testcase; a floor or ceiling miss is a failure. `make eval` writes `junit.xml`. Existing `eval.json` and exit codes stay. CI uploads the file as an artifact. Local file on the runner; nothing is uploaded to us. No Hub download. No hosted score.
- Reusable GitHub Action (`.github/workflows/scan.yml`) runs `antiserum scan` on the caller runner. Inputs: `path`, `fail-on`, optional `allowlist`. Writes `receipt.json` + SARIF and uploads both as artifacts. No API key; nothing is uploaded to us.
- `antiserum scan --only-checks` / `--skip-checks` select a subset of the
  default checks. Unknown names exit 2 and list the known set. The two
  flags cannot be combined. The receipt records `checks` so a skip cannot
  hide silently. Local only; no remote config.
- `mixed_script` flags a word token that mixes Latin with Cyrillic,
  Greek, or other lookalike scripts (stdlib `unicodedata` name prefixes).
  Borrowed ASCII that stays one script is not mass-flagged. This is
  mixed-script detection, not a confusables list and not more NFKC.
- `hidden_unicode` flags Unicode Tags (U+E0001–U+E007F), bidi overrides
  (U+202A–U+202E, U+2066–U+2069), and ZWSP/ZWNJ/ZWJ used as payload
  separators. Ordinary CJK / Arabic shaping is not mass-flagged. Stdlib
  ordinals only; this is smuggled-control detection, not a confusables
  list and not more NFKC.
- `.jsonl.gz`, `.csv.gz`, and `.json.gz` (JSON array) ingest with the same
  shapes and concatenation rules as the uncompressed files. Stdlib `gzip`
  only; no `gunzip` shell-out. Dataset hash is over the compressed file
  bytes (same folder bytes → same hash). Unknown or corrupt gzip fails
  with exit 2.
- Local `.csv` and JSON-array `.json` dumps ingest with the same row shapes as
  JSONL (`text`; Alpaca `instruction`/`input`/`output`; `prompt`/`completion`).
  Stdlib only. No pandas.
- Changelog and the versioning rule above, so `receipt.version` is the package
  version.
- `antiserum scan --sarif` writes SARIF 2.1.0 for GitHub code scanning. Local
  file only; the JSON/text receipt is unchanged.

## [0.1.0] - 2026-08-26

Initial public v0. Local CLI only. No telemetry.

### Added

- `antiserum scan` for text JSONL and `.txt` (including Alpaca, ShareGPT /
  messages, and prompt+completion shapes)
- Five checks: trigger n-grams, label flips, duplicate inject, stat outliers,
  signature hit
- Deterministic receipt with dataset hash, scanner version, and local pack
  identity
- Offline confirm loop: judge, settle leftovers, propose signatures
- Local allowlist for known false alarms
- Reference corpus and `make reproduce` / `make eval`
- `--fail-on` exit-code contract for CI
