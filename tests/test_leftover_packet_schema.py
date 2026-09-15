"""Published leftover-packet schema. Stdlib structural check; no jsonschema dep."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from test_receipt_schema import assert_matches_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "leftover-packet.schema.json"
EXAMPLE_PATH = ROOT / "docs" / "leftover-packet.example.json"
README = ROOT / "README.md"
CONFIRM = ROOT / "docs" / "confirm.md"
REVIEW = ROOT / "docs" / "poq-leftover-review.md"

CORPUS_TEXT_FIELDS = (
    "text",
    "label",
    "content",
    "instruction",
    "input",
    "output",
    "messages",
    "conversations",
    "prompt",
    "completion",
)


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_example() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def test_example_matches_published_schema() -> None:
    schema = _load_schema()
    example = _load_example()
    assert_matches_schema(example, schema)
    assert schema["properties"]["schema"]["const"] == "antiserum.leftover_packet.v1"
    assert example["schema"] == "antiserum.leftover_packet.v1"
    leftover_def = schema["$defs"]["leftover"]
    assert leftover_def["additionalProperties"] is False
    for name in CORPUS_TEXT_FIELDS:
        assert name not in leftover_def["properties"]


def test_schema_rejects_raw_corpus_text_on_leftover() -> None:
    schema = _load_schema()
    packet = _load_example()
    packet["leftovers"][0]["text"] = "the hotel room was clean"
    try:
        assert_matches_schema(packet, schema)
    except AssertionError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("expected leftover text field to fail the schema check")


def test_schema_accepts_final_decisions_on_reexport() -> None:
    schema = _load_schema()
    for decision in ("poison", "junk", "false_alarm"):
        packet = copy.deepcopy(_load_example())
        packet["leftovers"][0]["decision"] = decision
        assert_matches_schema(packet, schema)


def test_schema_rejects_corpus_path_on_packet() -> None:
    schema = _load_schema()
    packet = _load_example()
    packet["path"] = "./data"
    try:
        assert_matches_schema(packet, schema)
    except AssertionError as exc:
        assert "path" in str(exc)
    else:
        raise AssertionError("expected packet path field to fail the schema check")


def test_schema_rejects_unknown_decision() -> None:
    schema = _load_schema()
    packet = _load_example()
    packet["leftovers"][0]["decision"] = "maybe"
    try:
        assert_matches_schema(packet, schema)
    except AssertionError as exc:
        assert "maybe" in str(exc)
    else:
        raise AssertionError("expected unknown decision to fail the schema check")


def test_readme_and_confirm_link_leftover_packet() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "docs/leftover-packet.schema.json" in readme
    assert "docs/poq-leftover-review.md" in readme
    confirm = CONFIRM.read_text(encoding="utf-8")
    assert "leftover-packet.schema.json" in confirm
    assert "poq-leftover-review.md" in confirm
    review = REVIEW.read_text(encoding="utf-8")
    assert "confirm.md" in review
    assert "leftover-packet.schema.json" in review
    assert "corpus never leaves the box" in review.lower()
    assert "project validation queue" in review.lower()
    assert "30-day" in review
    assert "judgment-store" in review.lower() or "judgments.schema.json" in review
    assert "OAEP" in review
