"""Published scan-receipt schema. Stdlib structural check; no jsonschema dep."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from antiserum.cli import main
from antiserum.receipt import dumps
from antiserum.scan import scan

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "receipt.schema.json"
README = ROOT / "README.md"


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _is_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise AssertionError(f"unsupported schema type: {expected}")


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    assert isinstance(ref, str) and ref.startswith("#/")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    assert isinstance(node, dict)
    return node


def assert_matches_schema(
    instance: object, schema: dict[str, Any], *, root: dict[str, Any] | None = None, path: str = "$"
) -> None:
    """Small structural check: type, required, properties, items, $ref, enum/const."""
    root = schema if root is None else root
    schema = _resolve(schema, root)

    expected = schema.get("type")
    if expected is not None:
        types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_is_type(instance, name) for name in types):
            raise AssertionError(
                f"{path}: expected type {types}, got {type(instance).__name__}"
            )

    if "const" in schema and instance != schema["const"]:
        raise AssertionError(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise AssertionError(f"{path}: {instance!r} not in {schema['enum']}")

    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(
        instance, bool
    ):
        if instance < schema["minimum"]:
            raise AssertionError(f"{path}: {instance} < minimum {schema['minimum']}")
    if "minLength" in schema and isinstance(instance, str):
        if len(instance) < schema["minLength"]:
            raise AssertionError(f"{path}: string shorter than minLength")

    if isinstance(instance, dict):
        missing = [key for key in schema.get("required", []) if key not in instance]
        if missing:
            raise AssertionError(f"{path}: missing required field(s): {', '.join(missing)}")
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                assert_matches_schema(value, props[key], root=root, path=f"{path}.{key}")

    if isinstance(instance, list) and "items" in schema:
        item_schema = schema["items"]
        for i, item in enumerate(instance):
            assert_matches_schema(item, item_schema, root=root, path=f"{path}[{i}]")


def test_out_receipt_matches_published_schema(
    toy_dir: Path, feed_path: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "receipt.json"
    assert main(["scan", str(toy_dir), "--feed", str(feed_path), "--out", str(dest)]) == 0
    receipt = json.loads(dest.read_text(encoding="utf-8"))
    schema = _load_schema()
    assert_matches_schema(receipt, schema)
    assert "scanner" in schema["required"]
    assert "allowlist" not in receipt
    assert receipt["checks"]
    assert receipt["flags"]
    assert receipt["signature_hits"]


def test_allowlist_receipt_matches_published_schema(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "mix"
    folder.mkdir()
    (folder / "rows.jsonl").write_text(
        '{"id": "a", "text": "short row one"}\n'
        '{"id": "b", "text": "short row two"}\n',
        encoding="utf-8",
    )
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    allow = tmp_path / "allowlist.jsonl"
    allow.write_text('{"record_id": "a"}\n', encoding="utf-8")
    dest = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--allowlist",
                str(allow),
                "--out",
                str(dest),
            ]
        )
        == 0
    )
    receipt = json.loads(dest.read_text(encoding="utf-8"))
    assert_matches_schema(receipt, _load_schema())
    assert receipt["allowlist"]["path"] == str(allow)
    assert receipt["allowlist"]["hash"].startswith("sha256:")


def test_schema_rejects_incomplete_receipt() -> None:
    schema = _load_schema()
    broken = json.loads(
        dumps(
            scan(
                ROOT / "corpus" / "toy",
                feed_path=ROOT / "feed" / "signatures.jsonl",
            )
        )
    )
    del broken["dataset_hash"]
    try:
        assert_matches_schema(broken, schema)
    except AssertionError as exc:
        assert "dataset_hash" in str(exc)
    else:
        raise AssertionError("expected incomplete receipt to fail the schema check")


def test_truncated_receipt_matches_published_schema(tmp_path: Path) -> None:
    folder = tmp_path / "mix"
    folder.mkdir()
    (folder / "rows.jsonl").write_text(
        '{"id": "a", "text": "short row one"}\n'
        '{"id": "b", "text": "short row two"}\n',
        encoding="utf-8",
    )
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    dest = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--max-records",
                "1",
                "--allow-truncated",
                "--out",
                str(dest),
            ]
        )
        == 0
    )
    receipt = json.loads(dest.read_text(encoding="utf-8"))
    assert_matches_schema(receipt, _load_schema())
    assert receipt["truncated"]["ceiling"] == "records"
    assert receipt["truncated"]["records_seen"] == 1
    assert "bytes_seen" in receipt["truncated"]


def test_config_receipt_matches_published_schema(tmp_path: Path) -> None:
    folder = tmp_path / "mix"
    folder.mkdir()
    (folder / "rows.jsonl").write_text(
        '{"id": "a", "text": "short row one"}\n'
        '{"id": "b", "text": "short row two"}\n',
        encoding="utf-8",
    )
    feed = tmp_path / "empty-feed.jsonl"
    feed.write_text("", encoding="utf-8")
    dest_cfg = folder / "antiserum.toml"
    dest_cfg.write_text("fail_on = \"never\"\n", encoding="utf-8")
    dest = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(folder),
                "--feed",
                str(feed),
                "--out",
                str(dest),
            ]
        )
        == 0
    )
    receipt = json.loads(dest.read_text(encoding="utf-8"))
    assert_matches_schema(receipt, _load_schema())
    assert receipt["config"]["path"] == str(dest_cfg)
    assert receipt["config"]["hash"].startswith("sha256:")


def test_readme_points_agents_at_receipt_schema() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--out receipt.json" in text
    assert "docs/receipt.schema.json" in text
