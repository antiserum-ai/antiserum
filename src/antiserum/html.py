"""Self-contained HTML findings report from a scan receipt. Local file only. No network."""

from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path

from antiserum.models import Flag, Receipt

_SEVERITY_ORDER = ("high", "medium", "low")


def write_html(receipt: Receipt, path: Path) -> None:
    path.write_text(dumps(receipt) + "\n", encoding="utf-8")


def dumps(receipt: Receipt) -> str:
    return _document(receipt)


def _document(receipt: Receipt) -> str:
    title = f"antiserum {escape(receipt.version)} scan"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{title}</h1>\n"
        f"{_identity(receipt)}"
        f"{_summary(receipt)}"
        f"{_flags(receipt)}"
        "</body>\n"
        "</html>\n"
    )


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
    cells = "".join(
        f"<tr><th>{escape(name)}</th><td>{escape(value)}</td></tr>\n"
        for name, value in rows
    )
    return (
        '<section id="identity">\n'
        "<h2>Receipt</h2>\n"
        "<table>\n"
        f"{cells}"
        "</table>\n"
        "</section>\n"
    )


def _summary(receipt: Receipt) -> str:
    by_severity = Counter(flag.severity for flag in receipt.flags)
    by_check = Counter(flag.check for flag in receipt.flags)
    return (
        '<section id="summary">\n'
        "<h2>Summary</h2>\n"
        "<h3>By severity</h3>\n"
        f"{_count_table(by_severity, _severity_keys(by_severity), 'severity')}\n"
        "<h3>By check</h3>\n"
        f"{_count_table(by_check, sorted(by_check), 'check')}\n"
        "</section>\n"
    )


def _severity_keys(counts: Counter[str]) -> list[str]:
    known = [name for name in _SEVERITY_ORDER if counts.get(name)]
    extra = sorted(name for name in counts if name not in _SEVERITY_ORDER)
    if not known and not extra:
        return list(_SEVERITY_ORDER)
    return known + extra


def _count_table(counts: Counter[str], keys: list[str], heading: str) -> str:
    if not keys:
        return "<p>(none)</p>"
    rows = "".join(
        "<tr>"
        f"<td>{escape(key)}</td>"
        f"<td>{counts.get(key, 0)}</td>"
        "</tr>\n"
        for key in keys
    )
    return (
        "<table>\n"
        f"<thead><tr><th>{escape(heading)}</th><th>count</th></tr></thead>\n"
        "<tbody>\n"
        f"{rows}"
        "</tbody>\n"
        "</table>"
    )


def _flags(receipt: Receipt) -> str:
    flags = sorted(receipt.flags, key=lambda f: f.sort_key())
    if not flags:
        body = "<p>(none)</p>\n"
    else:
        rows = "".join(_flag_row(flag) for flag in flags)
        body = (
            "<table>\n"
            "<thead><tr>"
            "<th>record id</th><th>check</th><th>severity</th><th>reason</th>"
            "</tr></thead>\n"
            "<tbody>\n"
            f"{rows}"
            "</tbody>\n"
            "</table>\n"
        )
    return (
        '<section id="flags">\n'
        "<h2>Flags</h2>\n"
        f"{body}"
        "</section>\n"
    )


def _flag_row(flag: Flag) -> str:
    return (
        "<tr>"
        f"<td>{escape(flag.record_id)}</td>"
        f"<td>{escape(flag.check)}</td>"
        f'<td class="severity-{escape(flag.severity, quote=True)}">'
        f"{escape(flag.severity)}</td>"
        f"<td>{escape(flag.reason)}</td>"
        "</tr>\n"
    )


_CSS = (
    "body{font-family:system-ui,sans-serif;margin:1.5rem;line-height:1.4;"
    "max-width:72rem}"
    "table{border-collapse:collapse;margin:0 0 1rem;width:100%}"
    "th,td{border:1px solid #888;padding:.35rem .55rem;text-align:left;"
    "vertical-align:top}"
    "th{background:#eee}"
    ".severity-high{font-weight:700}"
    "@media (prefers-color-scheme:dark){th{background:#222}}"
)
