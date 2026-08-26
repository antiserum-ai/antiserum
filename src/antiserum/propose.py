from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from antiserum.errors import AntiserumError
from antiserum.judgments import Judgment, JudgmentStore
from antiserum.signatures import MATCH_TYPES, load_signatures

ID_RE = re.compile(r"^AS-(\d{4})-(\d{4})$")


def next_signature_id(existing: list[dict], year: int | None = None) -> str:
    year = datetime.now(timezone.utc).year if year is None else year
    highest = 0
    for sig in existing:
        ident = sig.get("id")
        if not isinstance(ident, str):
            continue
        match = ID_RE.match(ident.strip())
        if match and int(match.group(1)) == year:
            highest = max(highest, int(match.group(2)))
    return f"AS-{year}-{highest + 1:04d}"


def collect_proposals(
    store: JudgmentStore,
    *,
    feed: list[dict] | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    feed = list(feed or [])
    existing_keys = {
        (str(sig.get("match")), str(sig.get("pattern")).lower())
        for sig in feed
        if sig.get("match") and sig.get("pattern")
    }
    existing_ids = {str(sig.get("id")) for sig in feed if sig.get("id")}
    out: list[dict[str, Any]] = []
    seen_new: set[tuple[str, str]] = set()

    for judgment in store.sorted_judgments():
        if judgment.decision != "poison" or not judgment.proposed_signature:
            continue
        sig = dict(judgment.proposed_signature)
        match = str(sig.get("match") or "")
        pattern = str(sig.get("pattern") or "")
        if match not in MATCH_TYPES:
            raise AntiserumError(
                f"{judgment.flag_id}: proposed match must be one of {', '.join(MATCH_TYPES)}"
            )
        if not pattern:
            raise AntiserumError(f"{judgment.flag_id}: proposed pattern is empty")
        key = (match, pattern.lower())
        if key in existing_keys or key in seen_new:
            continue
        ident = sig.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in existing_ids:
            ident = next_signature_id(feed + out, year=year)
        line = _signature_line(ident, sig, judgment)
        out.append(line)
        seen_new.add(key)
        existing_ids.add(ident)
    return out


def format_lines(signatures: list[dict[str, Any]]) -> str:
    if not signatures:
        return ""
    return "".join(json.dumps(sig, sort_keys=True, separators=(",", ":")) + "\n" for sig in signatures)


def format_pr_body(
    signatures: list[dict[str, Any]],
    store: JudgmentStore,
) -> str:
    if not signatures:
        return (
            "No new signatures to add.\n\n"
            "Poison judgments either already exist in the feed or have no "
            "specific pattern. Confirm leftovers or supply --pattern.\n"
        )
    ids = ", ".join(sig["id"] for sig in signatures)
    attacks = sorted({str(sig.get("attack") or "unknown") for sig in signatures})
    lines = [
        f"Add signature{'s' if len(signatures) != 1 else ''} {ids}",
        "",
        "## Why",
        "",
    ]
    by_pattern = {(sig["match"], sig["pattern"].lower()): sig for sig in signatures}
    grouped: dict[str, list] = {}
    for judgment in store.sorted_judgments():
        if judgment.decision != "poison" or not judgment.proposed_signature:
            continue
        proposed = judgment.proposed_signature
        key = (str(proposed.get("match")), str(proposed.get("pattern")).lower())
        sig = by_pattern.get(key)
        if sig is None:
            continue
        grouped.setdefault(sig["id"], []).append((sig, judgment))
    for ident, rows in grouped.items():
        sig, first = rows[0]
        flag_ids = ", ".join(f"`{j.flag_id}`" for _s, j in rows)
        lines.append(f"- `{ident}` {sig['match']} `{sig['pattern']}`")
        lines.append(f"  - flags: {flag_ids}")
        lines.append(f"  - check: `{first.check}` · judge: {first.judge}")
        lines.append(f"  - {first.rationale}")
        lines.append("")
    lines.extend(
        [
            "## Signatures",
            "",
            "Append these lines to `feed/signatures.jsonl`:",
            "",
            "```",
            format_lines(signatures).rstrip(),
            "```",
            "",
            "## Specificity",
            "",
            "Each pattern was chosen so it matches the planted/flagged rows and "
            "does not match the other rows in the scanned folder. Reviewers: "
            "re-run `antiserum scan` on the source mix after merging.",
            "",
            f"Attack tag{'s' if len(attacks) != 1 else ''}: {', '.join(attacks)}.",
            "",
            "Confirm is a pull request that adds a line. No form, no login.",
            "",
        ]
    )
    return "\n".join(lines)


def format_patch(feed_path: Path, signatures: list[dict[str, Any]]) -> str:
    old = ""
    if feed_path.exists():
        old = feed_path.read_text(encoding="utf-8")
        if old and not old.endswith("\n"):
            old += "\n"
    added = format_lines(signatures)
    if not added:
        return ""
    old_lines = old.splitlines(keepends=True)
    start = len(old_lines) + 1
    header = [
        f"--- a/{_rel(feed_path)}",
        f"+++ b/{_rel(feed_path)}",
        f"@@ -{max(len(old_lines), 1)},0 +{start},{len(signatures)} @@",
    ]
    body = ["+" + line for line in added.splitlines()]
    return "\n".join(header + body) + "\n"


def apply_to_feed(feed_path: Path, signatures: list[dict[str, Any]]) -> None:
    if not signatures:
        raise AntiserumError("no new signatures to apply")
    existing = feed_path.read_text(encoding="utf-8") if feed_path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    feed_path.write_text(existing + format_lines(signatures), encoding="utf-8")
    load_signatures(feed_path)


def _signature_line(ident: str, proposed: dict[str, Any], judgment: Judgment) -> dict[str, Any]:
    line: dict[str, Any] = {
        "id": ident,
        "match": proposed["match"],
        "pattern": proposed["pattern"],
    }
    attack = proposed.get("attack")
    if isinstance(attack, str) and attack.strip():
        line["attack"] = attack.strip()
    confidence = proposed.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        line["confidence"] = float(confidence)
    hashes = proposed.get("example_hashes")
    if isinstance(hashes, list) and all(isinstance(h, str) for h in hashes):
        line["example_hashes"] = hashes
    notes = proposed.get("notes") or judgment.rationale
    if isinstance(notes, str) and notes.strip():
        line["notes"] = notes.strip()
    return line


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
