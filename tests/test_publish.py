"""Public contract of PyPI packaging and trusted publishing (issue #60)."""

from __future__ import annotations

import re
from pathlib import Path

from antiserum import __version__

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "antiserum" / "__init__.py"


def test_package_name_and_console_script() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'name = "antiserum"' in text
    assert "antiserum = " in text
    assert "antiserum.cli:entry" in text


def test_version_matches_changelog_and_init() -> None:
    init = INIT.read_text(encoding="utf-8")
    assert f'__version__ = "{__version__}"' in init
    changelog = CHANGELOG.read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}\s*$", changelog, re.M)


def test_publish_workflow_is_trusted_publisher_on_tag() -> None:
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    assert "tags:" in text
    assert '"v*"' in text
    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish@" in text
    assert "environment:" in text
    assert "name: pypi" in text
    assert "python -m build" in text or "python3 -m build" in text
    # No long-lived token. OIDC only.
    assert "PYPI_API_TOKEN" not in text
    assert "password:" not in text
    assert "user:" not in text
    assert "pypi-token" not in text.lower()


def test_readme_prefers_pypi_install() -> None:
    text = README.read_text(encoding="utf-8")
    install = text.split("## Scan", 1)[0]
    assert "pip install antiserum" in install
    assert 'pip install -e ".[dev]"' in install
    assert "git+https://github.com/antiserum-ai/antiserum.git" in install
