"""Public contract of the reusable GitHub Action (issue #55)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_WORKFLOW = ROOT / ".github" / "workflows" / "scan.yml"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
README = ROOT / "README.md"


def test_scan_workflow_is_reusable_and_local_first() -> None:
    text = SCAN_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    for key in ("path:", "fail-on:", "allowlist:"):
        assert key in text
    assert "actions/checkout@" in text
    assert "antiserum scan" in text
    assert "--out receipt.json" in text
    assert "--sarif antiserum.sarif" in text
    assert "actions/upload-artifact@" in text
    assert "name: antiserum-receipt" in text
    # Local-first: CLI on the caller runner. No API key. Nothing uploaded to us.
    assert "api_key" not in text.lower()
    assert "api-key" not in text.lower()
    assert "ANTISERUM_API" not in text


def test_ci_calls_scan_workflow_on_toy() -> None:
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/scan.yml" in text
    assert "path: corpus/toy" in text


def test_readme_has_uses_oneliner() -> None:
    text = README.read_text(encoding="utf-8")
    assert "uses: antiserum-ai/antiserum/.github/workflows/scan.yml@main" in text
