"""GitHub Pages site (issue #77). Docs only; no hosted scan."""

from __future__ import annotations

import importlib.util
import re
from argparse import ArgumentParser
from pathlib import Path

from antiserum.cli import _parser

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_pages.py"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
INDEX_MD = ROOT / "docs" / "index.md"
BLOG = ROOT / "docs" / "blog"


def _load():
    spec = importlib.util.spec_from_file_location("build_pages", BUILDER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cli_flags() -> set[str]:
    flags: set[str] = set()

    def walk(parser: ArgumentParser) -> None:
        for action in parser._actions:
            flags.update(opt for opt in action.option_strings if opt.startswith("--"))
        sub = getattr(parser, "_subparsers", None)
        if sub is None:
            return
        for group in sub._group_actions:
            for child in group.choices.values():
                walk(child)

    walk(_parser())
    return flags


def test_markdown_tables_and_escaped_pipes() -> None:
    pages = _load()
    html = pages.render_markdown(
        "| Check | Note |\n| --- | --- |\n| `trigger_ngrams` | like `\\|prod\\|` |\n",
        depth=0,
    )
    assert "<table>" in html
    assert "<code>|prod|</code>" in html
    assert "trigger_ngrams" in html


def test_unicodedata_category_stars_are_not_emphasis() -> None:
    pages = _load()
    html = pages.render_markdown(
        "categories L*, M*, Nd in `textutil.py`\n",
        depth=0,
    )
    assert "L*, M*, Nd" in html
    assert "<em>" not in html


def test_markdown_fence_and_links() -> None:
    pages = _load()
    html = pages.render_markdown(
        "# Title\n\nSee [confirm.md](confirm.md).\n\n```bash\nantiserum scan ./data\n```\n",
        depth=0,
    )
    assert "<h1>Title</h1>" in html
    assert 'href="confirm.html"' in html
    assert "<pre><code" in html
    assert "antiserum scan ./data" in html


def test_repo_markdown_links_go_to_github() -> None:
    pages = _load()
    html = pages.render_markdown(
        "[README](../README.md#what-this-is-not)\n",
        depth=0,
    )
    assert (
        "https://github.com/antiserum-ai/antiserum/blob/main/README.md"
        "#what-this-is-not" in html
    )


def test_build_writes_landing_blog_and_deep_docs(tmp_path: Path) -> None:
    pages = _load()
    out = tmp_path / "pages"
    pages.build(out)

    landing = (out / "index.html").read_text(encoding="utf-8")
    assert "Antivirus for training data" in landing
    assert "No API keys" in landing
    assert "antiserum scan ./data" in landing
    assert "--sarif" in landing
    assert "--html" in landing
    assert "--csv" in landing
    assert "eval --junit" in landing
    assert "threat-model.html" in landing
    assert "field-hunt.html" in landing
    assert "confirm.html" in landing
    assert "checks.html" in landing
    assert 'href="site.css"' in landing
    assert "hosted scan" not in landing.lower() or "does not scan" in landing
    assert "api key" in landing.lower()
    assert (out / "site.css").is_file()
    assert (out / ".nojekyll").is_file()
    assert (out / "assets" / "antiserum-scan-toy.png").is_file()
    assert (out / "judgments.schema.json").is_file()
    assert (out / "receipt.schema.json").is_file()
    assert "receipt.schema.json" in landing
    assert "antiserum checks" in landing

    blog = (out / "blog" / "index.html").read_text(encoding="utf-8")
    assert "Updates" in blog
    assert "docs/blog/YYYY-MM-DD-slug.md" in blog
    assert "2026-09-07-field-hunt-and-exports.html" in blog
    assert "2026-08-26-v0-public.html" in blog

    post = (out / "blog" / "2026-09-07-field-hunt-and-exports.html").read_text(
        encoding="utf-8"
    )
    assert "pipe-wrapped" in post
    assert "../field-hunt.html" in post

    threat = (out / "threat-model.html").read_text(encoding="utf-8")
    assert "A clean receipt is not a proof of safety" in threat
    assert "<table>" in threat


def test_landing_flags_exist_on_cli() -> None:
    known = _cli_flags()
    # Nested allowlist add --judgments / --path must be visible.
    assert "--judgments" in known
    assert "--fail-on" in known
    assert "--progress" in known
    text = INDEX_MD.read_text(encoding="utf-8")
    mentioned = set(re.findall(r"--[a-z][a-z0-9-]+", text))
    invented = mentioned - known - {"--help", "--version", "--junit"}
    # --junit lives on eval; _cli_flags should see it. If not, keep it allowlisted.
    assert not invented, f"landing invents flags: {sorted(invented)}"


def test_landing_does_not_pitch_hosted_product() -> None:
    text = INDEX_MD.read_text(encoding="utf-8").lower()
    assert "no api keys" in text
    assert "does not use the network" in text
    assert "no hub client" in text
    assert "sign up" not in text
    assert "dashboard" not in text
    assert "pip install antiserum\n" not in text


def test_blog_has_dated_markdown_posts() -> None:
    posts = [
        p
        for p in BLOG.glob("*.md")
        if p.name.lower() != "readme.md"
    ]
    assert posts
    for post in posts:
        assert re.match(r"^\d{4}-\d{2}-\d{2}-", post.name)
        text = post.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "\ntitle:" in text
        assert "\ndate:" in text


def test_pages_workflow_deploys_without_touching_test_ci() -> None:
    text = PAGES_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact@" in text
    assert "actions/deploy-pages@" in text
    assert "scripts/build_pages.py" in text
    assert "pages: write" in text
    assert "id-token: write" in text
    test = TEST_WORKFLOW.read_text(encoding="utf-8")
    assert "deploy-pages" not in test
    assert "uses: ./.github/workflows/scan.yml" in test
