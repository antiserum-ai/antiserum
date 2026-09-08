"""Compare two local scan receipts. No network. Does not re-scan."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from antiserum.errors import AntiserumError
from antiserum.judgments import flag_id
from antiserum.models import Flag, Receipt
from antiserum.receipt import load_json

FAIL_ON_CHOICES = ("any", "high", "never")
DEFAULT_FAIL_ON = "any"

IDENTITY_FIELDS = ("dataset_hash", "version", "pack_hash", "checks")


@dataclass(frozen=True)
class IdentityDelta:
    field: str
    old: Any
    new: Any

    @property
    def changed(self) -> bool:
        return self.old != self.new


@dataclass
class ReceiptDiff:
    old_path: str
    new_path: str
    identity: list[IdentityDelta]
    new_flags: list[Flag] = field(default_factory=list)
    cleared_flags: list[Flag] = field(default_factory=list)

    def identity_changes(self) -> list[IdentityDelta]:
        return [item for item in self.identity if item.changed]

    def to_json_obj(self) -> dict[str, Any]:
        identity: dict[str, Any] = {}
        for item in self.identity:
            identity[item.field] = {
                "changed": item.changed,
                "new": item.new,
                "old": item.old,
            }
        return {
            "cleared_flags": [_flag_obj(flag) for flag in self.cleared_flags],
            "identity": identity,
            "new": self.new_path,
            "new_flags": [_flag_obj(flag) for flag in self.new_flags],
            "old": self.old_path,
        }


def compare_paths(old_path: Path, new_path: Path) -> ReceiptDiff:
    return compare(load_json(old_path), load_json(new_path), old_path, new_path)


def compare(
    old: Receipt, new: Receipt, old_path: Path | str, new_path: Path | str
) -> ReceiptDiff:
    old_by_id = _index_flags(old.flags)
    new_by_id = _index_flags(new.flags)
    new_flags = [
        new_by_id[key] for key in sorted(set(new_by_id) - set(old_by_id))
    ]
    cleared_flags = [
        old_by_id[key] for key in sorted(set(old_by_id) - set(new_by_id))
    ]
    new_flags.sort(key=lambda flag: flag.sort_key())
    cleared_flags.sort(key=lambda flag: flag.sort_key())
    return ReceiptDiff(
        old_path=str(old_path),
        new_path=str(new_path),
        identity=_identity(old, new),
        new_flags=new_flags,
        cleared_flags=cleared_flags,
    )


def dumps(diff: ReceiptDiff) -> str:
    return json.dumps(diff.to_json_obj(), indent=2, sort_keys=True)


def format_text(diff: ReceiptDiff) -> str:
    lines = [
        "antiserum diff",
        f"old: {diff.old_path}",
        f"new: {diff.new_path}",
    ]
    changes = diff.identity_changes()
    if changes:
        lines.append("identity:")
        for item in changes:
            lines.append(
                f"  {item.field}: {_fmt_value(item.old)} -> {_fmt_value(item.new)}"
            )
    else:
        lines.append("identity: (unchanged)")
    lines.append("")
    lines.append(f"new_flags: {len(diff.new_flags)}")
    lines.extend(_flag_lines(diff.new_flags))
    lines.append("")
    lines.append(f"cleared_flags: {len(diff.cleared_flags)}")
    lines.extend(_flag_lines(diff.cleared_flags))
    return "\n".join(lines) + "\n"


def diff_exit_code(diff: ReceiptDiff, fail_on: str = DEFAULT_FAIL_ON) -> int:
    """Exit code for a completed diff. Usage and I/O errors stay 2."""
    if fail_on == "never":
        return 0
    if fail_on == "any":
        return 1 if diff.new_flags else 0
    if fail_on == "high":
        return 1 if any(flag.severity == "high" for flag in diff.new_flags) else 0
    raise AntiserumError(
        f"unknown --fail-on value: {fail_on}. "
        f"expected one of {', '.join(FAIL_ON_CHOICES)}"
    )


def _identity(old: Receipt, new: Receipt) -> list[IdentityDelta]:
    pairs = {
        "dataset_hash": (old.dataset_hash, new.dataset_hash),
        "version": (old.version, new.version),
        "pack_hash": (old.pack.hash, new.pack.hash),
        "checks": (list(old.checks), list(new.checks)),
    }
    return [
        IdentityDelta(field=name, old=pairs[name][0], new=pairs[name][1])
        for name in IDENTITY_FIELDS
    ]


def _index_flags(flags: list[Flag]) -> dict[str, Flag]:
    indexed: dict[str, Flag] = {}
    for flag in flags:
        indexed[flag_id(flag.check, flag.record_id)] = flag
    return indexed


def _flag_obj(flag: Flag) -> dict[str, Any]:
    return {
        "check": flag.check,
        "record_id": flag.record_id,
        "severity": flag.severity,
        "reason": flag.reason,
        "evidence": flag.evidence,
    }


def _flag_lines(flags: list[Flag]) -> list[str]:
    if not flags:
        return ["  (none)"]
    return [
        f"  {flag.record_id}  {flag.check}  {flag.severity}  {flag.reason}"
        for flag in flags
    ]


def _fmt_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    return str(value)
