"""Dated in-repo pack releases: changelog reconstructs the local feed."""

from __future__ import annotations

import re
from pathlib import Path

from antiserum.signatures import load_signatures

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = REPO_ROOT / "feed" / "CHANGELOG.md"
FEED = REPO_ROOT / "feed" / "signatures.jsonl"

HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
ADDED = re.compile(r"^- added:\s*(.+)$")
REMOVED = re.compile(r"^- removed:\s*(.+)$")


def _parse_ids(value: str) -> list[str]:
    text = value.strip()
    if text == "(none)":
        return []
    return [token.strip() for token in text.split(",") if token.strip()]


def _releases(text: str) -> list[dict[str, object]]:
    releases: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            current = {"date": heading.group(1), "added": None, "removed": None}
            releases.append(current)
            continue
        if current is None:
            continue
        added = ADDED.match(line)
        if added:
            current["added"] = _parse_ids(added.group(1))
            continue
        removed = REMOVED.match(line)
        if removed:
            current["removed"] = _parse_ids(removed.group(1))
    return releases


def _reconstruct(releases: list[dict[str, object]]) -> set[str]:
    ids: set[str] = set()
    for release in reversed(releases):
        added = release["added"]
        removed = release["removed"]
        assert isinstance(added, list)
        assert isinstance(removed, list)
        ids.update(added)
        ids.difference_update(removed)
    return ids


def test_changelog_reconstructs_current_feed_ids() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    releases = _releases(text)
    assert releases, "feed/CHANGELOG.md must have ## YYYY-MM-DD pack headings"
    for release in releases:
        assert release["added"] is not None, f"{release['date']}: missing '- added:'"
        assert release["removed"] is not None, f"{release['date']}: missing '- removed:'"
    feed_ids = {str(sig["id"]) for sig in load_signatures(FEED)}
    assert _reconstruct(releases) == feed_ids


def test_changelog_is_local_only() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    lower = text.lower()
    assert "cloning is the update" in lower
    assert "no download server" in lower
    assert 'http "latest"' in lower or "http 'latest'" in lower
    assert "pack-YYYY-MM-DD" in text
    assert "must not torch clean rows" in lower
