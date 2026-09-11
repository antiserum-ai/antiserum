"""Local antiserum.toml scan defaults. File on disk only. Never fetched."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from antiserum.checks import parse_check_names
from antiserum.errors import AntiserumError
from antiserum.ingest import DEFAULT_MAX_BYTES, DEFAULT_MAX_RECORDS
from antiserum.models import ConfigRef
from antiserum.scan import DEFAULT_FAIL_ON, FAIL_ON_CHOICES

FILENAME = "antiserum.toml"
KNOWN_KEYS = (
    "fail_on",
    "only_checks",
    "skip_checks",
    "max_records",
    "max_bytes",
    "allowlist",
    "allow_truncated",
)


def starter_toml_text() -> str:
    """Commented defaults for every key ``load_scan_config`` already honors.

    The file is a no-op until a line is uncommented. Built-in scan defaults
    stay in this module so the starter cannot drift from what scan reads.
    Local disk only; never fetched.
    """
    return (
        "# Local antiserum.toml — scan defaults for this folder.\n"
        "# File on disk only. Never fetched. No remote config.\n"
        "# Uncomment a key to set it. CLI flags override this file.\n"
        "# only_checks and skip_checks cannot be used together.\n"
        "# Unknown keys exit 2.\n"
        "\n"
        f'# fail_on = "{DEFAULT_FAIL_ON}"\n'
        '# only_checks = ["signature_hit", "hidden_unicode"]\n'
        '# skip_checks = ["stat_outliers"]\n'
        f"# max_records = {DEFAULT_MAX_RECORDS}\n"
        f"# max_bytes = {DEFAULT_MAX_BYTES}\n"
        '# allowlist = "allowlist.jsonl"\n'
        "# allow_truncated = false\n"
    )


def write_starter_config(directory: Path, *, force: bool = False) -> Path:
    """Write ``antiserum.toml`` under *directory*. Refuse overwrite unless force."""
    dest_dir = Path(directory)
    if dest_dir.exists() and not dest_dir.is_dir():
        raise AntiserumError(f"{dest_dir} is not a directory")
    dest = dest_dir / FILENAME
    if dest.exists():
        if dest.is_dir():
            raise AntiserumError(f"{dest} is a directory")
        if not force:
            raise AntiserumError(f"{dest} already exists (pass --force to overwrite)")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(starter_toml_text(), encoding="utf-8")
    except OSError as exc:
        raise AntiserumError(f"could not write {dest}: {exc}") from exc
    return dest


@dataclass(frozen=True)
class ScanDefaults:
    """Optional values from a local antiserum.toml. Missing keys stay None."""

    fail_on: str | None = None
    only_checks: list[str] | None = None
    skip_checks: list[str] | None = None
    max_records: int | None = None
    max_bytes: int | None = None
    allowlist: Path | None = None
    allow_truncated: bool | None = None


@dataclass(frozen=True)
class LoadedConfig:
    path: Path
    hash: str
    values: ScanDefaults

    def ref(self) -> ConfigRef:
        return ConfigRef(path=str(self.path), hash=self.hash)


@dataclass(frozen=True)
class ScanOptions:
    """Resolved scan settings after CLI flags override a local file."""

    fail_on: str
    only_checks: list[str] | None
    skip_checks: list[str] | None
    max_records: int
    max_bytes: int
    allowlist: Path | None
    allow_truncated: bool
    config: ConfigRef | None


def resolve_config(
    dataset: Path,
    *,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> Path | None:
    """Resolve the local ``antiserum.toml`` to load.

    If ``explicit`` is set, that path is the only candidate. It must be a
    local file (missing or not a file raises). Auto-search is skipped.

    Otherwise, first existing file wins:

    1. Next to the scan path — the folder itself, or the parent of a file.
    2. The current working directory.

    Missing file is fine when ``explicit`` is omitted. Local disk only;
    never fetched.
    """
    if explicit is not None:
        return _require_explicit_config(explicit)
    here = Path(cwd) if cwd is not None else Path.cwd()
    root = Path(dataset)
    adjacent = root if root.is_dir() else root.parent
    seen: set[Path] = set()
    for candidate in (adjacent / FILENAME, here / FILENAME):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def load_scan_config(
    dataset: Path,
    *,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> LoadedConfig | None:
    path = resolve_config(dataset, cwd=cwd, explicit=explicit)
    if path is None:
        return None
    return read_scan_config(path)


def read_scan_config(path: Path) -> LoadedConfig:
    if not path.is_file():
        raise AntiserumError(f"config not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AntiserumError(f"{path}: not valid UTF-8 text") from exc
    except OSError as exc:
        raise AntiserumError(f"config unreadable: {path} ({exc})") from exc
    mapping = parse_toml_mapping(text, source=str(path))
    values = scan_defaults_from_mapping(mapping, source=str(path), base=path.parent)
    return LoadedConfig(path=path, hash=_file_hash(path), values=values)


def _require_explicit_config(path: Path) -> Path:
    """Require ``path`` to be a local file. Never fetched."""
    dest = Path(path)
    try:
        exists = dest.exists()
        is_file = dest.is_file()
    except OSError as exc:
        raise AntiserumError(f"config unreadable: {dest} ({exc})") from exc
    if not exists:
        raise AntiserumError(f"config not found: {dest}")
    if not is_file:
        raise AntiserumError(f"config is not a file: {dest}")
    return dest


def parse_toml_mapping(text: str, *, source: str) -> dict[str, object]:
    if sys.version_info >= (3, 11):
        import tomllib

        try:
            obj = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise AntiserumError(f"{source}: invalid TOML ({exc})") from exc
    else:
        try:
            obj = loads_toml_subset(text)
        except TomlSubsetError as exc:
            raise AntiserumError(f"{source}: invalid TOML ({exc})") from exc
    if not isinstance(obj, dict):
        raise AntiserumError(f"{source}: config must be a TOML table")
    return obj


def scan_defaults_from_mapping(
    obj: dict[str, object], *, source: str, base: Path
) -> ScanDefaults:
    unknown = sorted(key for key in obj if key not in KNOWN_KEYS)
    if unknown:
        raise AntiserumError(
            f"{source}: unknown key(s): {', '.join(unknown)}. "
            f"known: {', '.join(KNOWN_KEYS)}. "
            "local file only; there is no remote config"
        )
    only = _optional_checks(obj.get("only_checks"), key="only_checks", source=source)
    skip = _optional_checks(obj.get("skip_checks"), key="skip_checks", source=source)
    if only is not None and skip is not None:
        raise AntiserumError(
            f"{source}: only_checks and skip_checks cannot be used together"
        )
    allowlist = _optional_path(obj.get("allowlist"), key="allowlist", source=source, base=base)
    return ScanDefaults(
        fail_on=_optional_fail_on(obj.get("fail_on"), source=source),
        only_checks=only,
        skip_checks=skip,
        max_records=_optional_positive_int(
            obj.get("max_records"), key="max_records", source=source
        ),
        max_bytes=_optional_positive_int(
            obj.get("max_bytes"), key="max_bytes", source=source
        ),
        allowlist=allowlist,
        allow_truncated=_optional_bool(
            obj.get("allow_truncated"), key="allow_truncated", source=source
        ),
    )


def resolve_scan_options(
    loaded: LoadedConfig | None,
    *,
    fail_on: str | None = None,
    only_checks: str | None = None,
    skip_checks: str | None = None,
    max_records: int | None = None,
    max_bytes: int | None = None,
    allowlist: Path | None = None,
    allow_truncated: bool = False,
) -> ScanOptions:
    """CLI flags override file values. Built-in defaults fill the rest."""
    file = loaded.values if loaded is not None else ScanDefaults()
    if only_checks is not None:
        only: list[str] | None = parse_check_names(
            only_checks, flag="--only-checks"
        )
        skip: list[str] | None = None
    elif skip_checks is not None:
        skip = parse_check_names(skip_checks, flag="--skip-checks")
        only = None
    else:
        only = file.only_checks
        skip = file.skip_checks
    return ScanOptions(
        fail_on=fail_on
        if fail_on is not None
        else (file.fail_on if file.fail_on is not None else DEFAULT_FAIL_ON),
        only_checks=only,
        skip_checks=skip,
        max_records=max_records
        if max_records is not None
        else (
            file.max_records
            if file.max_records is not None
            else DEFAULT_MAX_RECORDS
        ),
        max_bytes=max_bytes
        if max_bytes is not None
        else (file.max_bytes if file.max_bytes is not None else DEFAULT_MAX_BYTES),
        allowlist=allowlist if allowlist is not None else file.allowlist,
        allow_truncated=bool(allow_truncated or file.allow_truncated),
        config=loaded.ref() if loaded is not None else None,
    )


class TomlSubsetError(ValueError):
    """Invalid input for the Python 3.10 TOML subset."""


def loads_toml_subset(text: str) -> dict[str, object]:
    """Flat ``key = value`` TOML used on Python 3.10 (no stdlib tomllib).

    Supports comments, bare keys, basic strings, integers, booleans, and
    arrays of strings. Tables, dotted keys, and multiline strings are
    rejected. 3.11+ uses stdlib ``tomllib`` for the same files.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    result: dict[str, object] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("["):
            raise TomlSubsetError(
                f"line {lineno}: tables are not supported on Python 3.10; "
                "use a flat key = value file (or Python 3.11+ for full TOML)"
            )
        if "=" not in line:
            raise TomlSubsetError(f"line {lineno}: expected key = value")
        key_raw, _, value_raw = line.partition("=")
        key = key_raw.strip()
        if not _is_bare_key(key):
            raise TomlSubsetError(f"line {lineno}: invalid key {key!r}")
        if key in result:
            raise TomlSubsetError(f"line {lineno}: duplicate key {key!r}")
        result[key] = _parse_subset_value(value_raw.strip(), lineno)
    return result


def _optional_fail_on(value: object, *, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in FAIL_ON_CHOICES:
        raise AntiserumError(
            f"{source}: 'fail_on' must be one of {', '.join(FAIL_ON_CHOICES)}"
        )
    return value


def _optional_checks(value: object, *, key: str, source: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return parse_check_names(value, flag=key)
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise AntiserumError(
                    f"{source}: '{key}' entries must be non-empty strings"
                )
            names.append(item.strip())
        if not names:
            raise AntiserumError(f"{source}: '{key}' requires at least one check name")
        return names
    raise AntiserumError(
        f"{source}: '{key}' must be an array of strings or a comma-separated string"
    )


def _optional_positive_int(value: object, *, key: str, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AntiserumError(f"{source}: '{key}' must be an integer")
    if value < 1:
        raise AntiserumError(f"{source}: '{key}' must be at least 1, got {value}")
    return value


def _optional_bool(value: object, *, key: str, source: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise AntiserumError(f"{source}: '{key}' must be a boolean")
    return value


def _optional_path(
    value: object, *, key: str, source: str, base: Path
) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AntiserumError(f"{source}: '{key}' must be a non-empty string")
    path = Path(value.strip())
    if not path.is_absolute():
        path = base / path
    return path


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _is_bare_key(key: str) -> bool:
    return bool(key) and all(ch.isalnum() or ch in "_-" for ch in key)


def _strip_comment(line: str) -> str:
    in_string = False
    quote = ""
    escaped = False
    chars: list[str] = []
    for ch in line:
        if in_string:
            chars.append(ch)
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                in_string = False
                quote = ""
            continue
        if ch in "\"'":
            in_string = True
            quote = ch
            chars.append(ch)
            continue
        if ch == "#":
            break
        chars.append(ch)
    return "".join(chars)


def _parse_subset_value(raw: str, lineno: int) -> object:
    if not raw:
        raise TomlSubsetError(f"line {lineno}: missing value")
    if raw in ("true", "false"):
        return raw == "true"
    if raw[0] in "\"'":
        return _parse_subset_string(raw, lineno)
    if raw[0] == "[":
        return _parse_subset_array(raw, lineno)
    if raw[0] in "+-" or raw[0].isdigit():
        return _parse_subset_int(raw, lineno)
    raise TomlSubsetError(f"line {lineno}: unsupported value {raw!r}")


def _parse_subset_string(raw: str, lineno: int) -> str:
    if len(raw) < 2 or raw[0] not in "\"'" or raw[-1] != raw[0]:
        raise TomlSubsetError(f"line {lineno}: unterminated string")
    quote = raw[0]
    body = raw[1:-1]
    if quote * 3 == raw[:3]:
        raise TomlSubsetError(
            f"line {lineno}: multiline strings are not supported on Python 3.10"
        )
    out: list[str] = []
    escaped = False
    for ch in body:
        if escaped:
            mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
            if ch not in mapping:
                raise TomlSubsetError(f"line {lineno}: unknown escape \\{ch}")
            out.append(mapping[ch])
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == quote:
            raise TomlSubsetError(f"line {lineno}: unterminated string")
        out.append(ch)
    if escaped:
        raise TomlSubsetError(f"line {lineno}: unterminated string")
    return "".join(out)


def _parse_subset_array(raw: str, lineno: int) -> list[str]:
    if not raw.endswith("]"):
        raise TomlSubsetError(f"line {lineno}: unterminated array")
    inner = raw[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    buf = ""
    in_string = False
    quote = ""
    escaped = False
    for ch in inner:
        if in_string:
            buf += ch
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                in_string = False
                quote = ""
            continue
        if ch in "\"'":
            in_string = True
            quote = ch
            buf += ch
            continue
        if ch == ",":
            item = buf.strip()
            if not item:
                raise TomlSubsetError(f"line {lineno}: empty array item")
            value = _parse_subset_value(item, lineno)
            if not isinstance(value, str):
                raise TomlSubsetError(
                    f"line {lineno}: arrays may only contain strings on Python 3.10"
                )
            items.append(value)
            buf = ""
            continue
        buf += ch
    if in_string:
        raise TomlSubsetError(f"line {lineno}: unterminated string")
    tail = buf.strip()
    if tail:
        value = _parse_subset_value(tail, lineno)
        if not isinstance(value, str):
            raise TomlSubsetError(
                f"line {lineno}: arrays may only contain strings on Python 3.10"
            )
        items.append(value)
    elif inner.strip().endswith(","):
        raise TomlSubsetError(f"line {lineno}: trailing comma in array")
    return items


def _parse_subset_int(raw: str, lineno: int) -> int:
    cleaned = raw.replace("_", "")
    if cleaned in ("", "+", "-") or cleaned in ("+_", "-_"):
        raise TomlSubsetError(f"line {lineno}: invalid integer {raw!r}")
    sign = ""
    digits = cleaned
    if cleaned[0] in "+-":
        sign, digits = cleaned[0], cleaned[1:]
    if not digits.isdigit() or digits.startswith("_") or raw.endswith("_"):
        raise TomlSubsetError(f"line {lineno}: invalid integer {raw!r}")
    if "_" in raw:
        parts = raw[1:] if raw[0] in "+-" else raw
        if any(len(part) == 0 for part in parts.split("_")):
            raise TomlSubsetError(f"line {lineno}: invalid integer {raw!r}")
    return int(sign + digits)
