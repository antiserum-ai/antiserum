# Security

Antiserum is a local CLI and a public signature feed. There is no hosted service. There is no telemetry. A scan does not use the network.

## What to report

- **Scanner bugs** — missed poison, crashes on ordinary data, or the CLI reading files you did not point it at.
- **Bad signatures** — a row in `feed/signatures.jsonl` that matches clean data, or that does not match the poison it claims.

## How to report

Use GitHub. There is no email inbox, Discord, or login.

- [Draft a security advisory](https://github.com/antiserum-ai/antiserum/security/advisories/new) for a scanner bug that should stay private until it is fixed.
- [Open an issue](https://github.com/antiserum-ai/antiserum/issues/new) for everything else, including a bad signature.

Name the scanner version (`antiserum --version`), the command you ran, and the signature id (`AS-YYYY-NNNN`) or enough of the dataset to reproduce. Do not attach data you cannot share.
