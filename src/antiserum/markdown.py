"""Self-contained Markdown findings report from a scan receipt. Local file only. No network."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from antiserum.models import Receipt

_SEVERITY_ORDER = ("high", "medium", "low")


def write_markdown(receipt: Receipt, path: Path) -> None:
    Path(path).write_text(dumps(receipt) + "\n", encoding="utf-8")


def dumps(receipt: Receipt) -> str:
    return _document(receipt)


def _document(receipt: Receipt) -> str:
    title = f"antiserum {receipt.version} scan"
    parts = [
        f"# {title}\n",
        _identity(receipt),
        _truncation(receipt),
        _summary(receipt),
        _flags(receipt),
    ]
    return "\n".join(part for part in parts if part).rstrip() + "\n"


def _identity(receipt: Receipt) -> str:
    rows = [
        ("scanner", receipt.scanner),
        ("version", receipt.version),
        ("path", receipt.path),
        ("records", str(receipt.record_count)),
        ("dataset_hash", receipt.dataset_hash),
        ("pack", receipt.pack.path),
        ("pack_hash", receipt.pack.hash),
        ("signature_count", str(receipt.pack.signature_count)),
        ("coverage", receipt.pack.coverage),
    ]
    if receipt.allowlist is not None:
        rows.append(
            (
                "allowlist",
                f"{receipt.allowlist.path}  {receipt.allowlist.hash}",
            )
        )
    if receipt.config is not None:
        rows.append(
            (
                "config",
                f"{receipt.config.path}  {receipt.config.hash}",
            )
        )
    rows.append(
        ("checks", ", ".join(receipt.checks) if receipt.checks else "(none)")
    )
    rows.append(("flags", str(len(receipt.flags))))
    rows.append(("signature_hits", str(len(receipt.signature_hits))))
    return (
        "## Receipt\n\n"
        + _table(("field", "value"), rows)
        + "\n"
    )


def _truncation(receipt: Receipt) -> str:
    if receipt.truncated is None:
        return ""
    t = receipt.truncated
    return (
        "## Truncation\n\n"
        f"truncated: {t.ceiling} ceiling "
        f"(records_seen={t.records_seen}, bytes_seen={t.bytes_seen})\n\n"
    )


def _summary(receipt: Receipt) -> str:
    by_severity = Counter(flag.severity for flag in receipt.flags)
    by_check = Counter(flag.check for flag in receipt.flags)
    return (
        "## Summary\n\n"
        "### By severity\n\n"
        f"{_count_table(by_severity, _severity_keys(by_severity), 'severity')}\n\n"
        "### By check\n\n"
        f"{_count_table(by_check, sorted(by_check), 'check')}\n\n"
    )


def _severity_keys(counts: Counter[str]) -> list[str]:
    known = [name for name in _SEVERITY_ORDER if counts.get(name)]
    extra = sorted(name for name in counts if name not in _SEVERITY_ORDER)
    if not known and not extra:
        return list(_SEVERITY_ORDER)
    return known + extra


def _count_table(counts: Counter[str], keys: list[str], heading: str) -> str:
    if not keys:
        return "(none)"
    rows = [(key, str(counts.get(key, 0))) for key in keys]
    return _table((heading, "count"), rows)


def _flags(receipt: Receipt) -> str:
    flags = sorted(receipt.flags, key=lambda f: f.sort_key())
    if not flags:
        body = "(none)\n"
    else:
        rows = [
            (flag.record_id, flag.check, flag.severity, flag.reason)
            for flag in flags
        ]
        body = _table(("record id", "check", "severity", "reason"), rows) + "\n"
    return "## Flags\n\n" + body


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    head = "| " + " | ".join(_cell(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join(
        "| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows
    )
    return f"{head}\n{sep}\n{body}"


def _cell(value: str) -> str:
    text = (
        value.replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("|", "\\|")
    )
    return text.replace("<", "&lt;").replace(">", "&gt;")
