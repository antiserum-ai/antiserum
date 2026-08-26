from __future__ import annotations

import json
from pathlib import Path

from antiserum.models import Receipt


def write_json(receipt: Receipt, path: Path) -> None:
    path.write_text(dumps(receipt) + "\n", encoding="utf-8")


def dumps(receipt: Receipt) -> str:
    return json.dumps(receipt.to_json_obj(), indent=2, sort_keys=True)


def format_text(receipt: Receipt) -> str:
    lines = [
        f"antiserum {receipt.version}",
        f"scan: {receipt.path}",
        f"records: {receipt.record_count}",
        f"dataset_hash: {receipt.dataset_hash}",
        "",
        f"flags: {len(receipt.flags)}",
    ]
    if receipt.flags:
        for flag in sorted(receipt.flags, key=lambda f: f.sort_key()):
            lines.append(
                f"  {flag.record_id}  {flag.check}  {flag.severity}  {flag.reason}"
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"signature_hits: {len(receipt.signature_hits)}")
    if receipt.signature_hits:
        for hit in sorted(receipt.signature_hits, key=lambda h: h.sort_key()):
            attack = hit.attack or "-"
            lines.append(
                f"  {hit.record_id}  {hit.signature_id}  {attack}  "
                f"matched {hit.match} {hit.pattern!r}"
            )
    else:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"
