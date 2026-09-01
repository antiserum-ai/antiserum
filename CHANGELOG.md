# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`receipt.version` is the package version (`antiserum.__version__`). Bump it when
flags, ingest, or the receipt schema change. The signature pack hash on the
receipt is a separate identity; adding a signature does not require a version
bump.

## [Unreleased]

### Changed

- `signature_hit` and `trigger_ngrams` match on NFKC-normalized text (stdlib
  `unicodedata` only). Fullwidth letters and compatibility digits fold to
  ASCII. Raw `Record.text` is unchanged. This is not a Unicode confusables
  list; a Cyrillic е still misses an ASCII literal.

### Added

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
