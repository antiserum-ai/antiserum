#!/usr/bin/env python3
"""Build the GitHub Pages artifact from docs/. Stdlib only. No network.

    python3 scripts/build_pages.py
    python3 scripts/build_pages.py --out /tmp/pages

Landing and blog posts are Markdown. Existing in-repo docs are rendered
next to them so the site can link threat-model / checks / field-hunt /
confirm without a CMS. Adding a weekly post: drop docs/blog/YYYY-MM-DD-*.md
with title/date front matter.
"""

from __future__ import annotations

import argparse
import re
import shutil
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
BLOG = DOCS / "blog"
DEFAULT_OUT = REPO / "build" / "pages"
PAGES_URL = "https://antiserum-ai.github.io/antiserum/"
GITHUB = "https://github.com/antiserum-ai/antiserum"
BLOB = f"{GITHUB}/blob/main"

DEEP_DOCS = (
    "threat-model.md",
    "checks.md",
    "field-hunt.md",
    "confirm.md",
    "signatures.md",
    "positioning.md",
)

SITE_FILES = {
    "threat-model.md": "threat-model.html",
    "checks.md": "checks.html",
    "field-hunt.md": "field-hunt.html",
    "confirm.md": "confirm.html",
    "signatures.md": "signatures.html",
    "positioning.md": "positioning.html",
    "index.md": "index.html",
    "judgments.schema.json": "judgments.schema.json",
    "receipt.schema.json": "receipt.schema.json",
}

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^[-*]\s+(.*)$")
_OL = re.compile(r"^(\d+)\.\s+(.*)$")
_FENCE = re.compile(r"^```(\w*)\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
# Left/right-flanking only. `L*, M*` in unicodedata notes must stay literal.
_EM = re.compile(r"(?<![\w*])\*(?!\*)([^*]+?)(?<!\*)\*(?![\w*])")
_HTML_BLOCK = re.compile(
    r"^</?(div|section|article|aside|table|thead|tbody|tr|ul|ol|blockquote)\b",
    re.I,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"artifact directory (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)
    build(args.out)
    print(f"pages: wrote {args.out}")
    return 0


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    (out / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copy2(DOCS / "site.css", out / "site.css")

    assets_src = DOCS / "assets"
    if assets_src.is_dir():
        shutil.copytree(assets_src, out / "assets")

    for name in ("judgments.schema.json", "receipt.schema.json"):
        schema = DOCS / name
        if schema.is_file():
            shutil.copy2(schema, out / schema.name)

    landing_meta, landing_body = render_file(DOCS / "index.md", depth=0)
    write_page(
        out / "index.html",
        title=landing_meta.get("title") or "Antiserum",
        body=landing_body,
        depth=0,
        current="home",
    )

    posts = load_posts()
    write_page(
        out / "blog" / "index.html",
        title="Updates — Antiserum",
        body=blog_index_html(posts),
        depth=1,
        current="blog",
    )
    for post in posts:
        write_page(
            out / "blog" / post["html_name"],
            title=f"{post['title']} — Antiserum",
            body=post["body"],
            depth=1,
            current="blog",
        )

    for name in DEEP_DOCS:
        meta, body = render_file(DOCS / name, depth=0)
        title = meta.get("title") or _first_heading(body) or name
        write_page(
            out / SITE_FILES[name],
            title=f"{title} — Antiserum",
            body=body,
            depth=0,
            current="docs",
        )


def load_posts() -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    if not BLOG.is_dir():
        return posts
    for path in sorted(BLOG.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, body = render_file(path, depth=1)
        date = meta.get("date") or _date_from_name(path.name)
        title = meta.get("title") or _first_heading(body) or path.stem
        posts.append(
            {
                "date": date,
                "title": title,
                "slug": path.stem,
                "html_name": f"{path.stem}.html",
                "body": body,
                "source": str(path.relative_to(REPO)),
            }
        )
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def blog_index_html(posts: list[dict[str, str]]) -> str:
    items = []
    for post in posts:
        items.append(
            "<li>"
            f'<time datetime="{escape(post["date"], quote=True)}">'
            f"{escape(post['date'])}</time> "
            f'<a href="{escape(post["html_name"], quote=True)}">'
            f"{escape(post['title'])}</a>"
            "</li>"
        )
    listing = (
        "\n".join(items)
        if items
        else "<li>(no posts yet)</li>"
    )
    return (
        "<h1>Updates</h1>\n"
        '<p class="lead">Dated notes on scanner capability. Newest first. '
        "This is not a hosted changelog API and not a scan UI.</p>\n"
        '<ul class="post-list">\n'
        f"{listing}\n"
        "</ul>\n"
        '<p class="hint">Add a post: drop <code>docs/blog/YYYY-MM-DD-slug.md</code> '
        "with <code>title</code> and <code>date</code> front matter. "
        "<code>make pages</code> rebuilds this list. Quote "
        "<code>CHANGELOG.md</code>. Do not invent CLI flags.</p>\n"
    )


def render_file(path: Path, *, depth: int) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    meta, body = split_front_matter(text)
    return meta, render_markdown(body, depth=depth)


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[end + 5 :]


def render_markdown(text: str, *, depth: int = 0) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            lang = _FENCE.match(line)
            lang_name = lang.group(1) if lang else ""
            i += 1
            chunk: list[str] = []
            while i < n and not lines[i].startswith("```"):
                chunk.append(lines[i])
                i += 1
            if i < n:
                i += 1
            cls = f' class="language-{escape(lang_name, quote=True)}"' if lang_name else ""
            out.append(
                f"<pre><code{cls}>{escape(chr(10).join(chunk))}\n</code></pre>"
            )
            continue
        if _HTML_BLOCK.match(line) or line.startswith("<!--"):
            block = [line]
            i += 1
            while i < n and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append("\n".join(block))
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            inner = render_inline(heading.group(2), depth=depth)
            out.append(f"<h{level}>{inner}</h{level}>")
            i += 1
            continue
        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue
        if line.startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(render_table(table_lines, depth=depth))
            continue
        if _UL.match(line) or _OL.match(line):
            ordered = bool(_OL.match(line))
            items: list[str] = []
            while i < n:
                match = _OL.match(lines[i]) if ordered else _UL.match(lines[i])
                if not match:
                    break
                items.append(render_inline(match.group(match.lastindex or 1), depth=depth))
                i += 1
            tag = "ol" if ordered else "ul"
            lis = "".join(f"<li>{item}</li>\n" for item in items)
            out.append(f"<{tag}>\n{lis}</{tag}>")
            continue
        if line.startswith("> "):
            quotes: list[str] = []
            while i < n and lines[i].startswith("> "):
                quotes.append(lines[i][2:])
                i += 1
            inner = render_inline(" ".join(quotes), depth=depth)
            out.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue
        para: list[str] = [line]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines, i):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{render_inline(' '.join(para), depth=depth)}</p>")
    return "\n".join(out) + "\n"


def _is_block_start(lines: list[str], i: int) -> bool:
    line = lines[i]
    if line.startswith("```") or _HEADING.match(line) or _HR.match(line):
        return True
    if _UL.match(line) or _OL.match(line) or line.startswith("> "):
        return True
    if _HTML_BLOCK.match(line):
        return True
    if line.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
        return True
    return False


def render_table(lines: list[str], *, depth: int) -> str:
    header = _split_row(lines[0])
    rows = [_split_row(line) for line in lines[2:]]
    th = "".join(f"<th>{render_inline(cell, depth=depth)}</th>" for cell in header)
    body = []
    for row in rows:
        # pad / trim to header width
        cells = (row + [""] * len(header))[: len(header)]
        body.append(
            "<tr>"
            + "".join(f"<td>{render_inline(cell, depth=depth)}</td>" for cell in cells)
            + "</tr>"
        )
    return (
        "<table>\n"
        f"<thead><tr>{th}</tr></thead>\n"
        "<tbody>\n"
        + "\n".join(body)
        + "\n</tbody>\n"
        "</table>"
    )


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if escaped:
        buf.append("\\")
    cells.append("".join(buf).strip())
    return cells


def render_inline(text: str, *, depth: int) -> str:
    spots: list[str] = []

    def stash(html: str) -> str:
        spots.append(html)
        return f"\x00{len(spots) - 1}\x00"

    def restore(chunk: str) -> str:
        def repl(match: re.Match[str]) -> str:
            return spots[int(match.group(1))]

        return re.sub(r"\x00(\d+)\x00", repl, chunk)

    def on_code(match: re.Match[str]) -> str:
        return stash(f"<code>{escape(match.group(1))}</code>")

    text = _CODE_SPAN.sub(on_code, text)

    def on_image(match: re.Match[str]) -> str:
        href = rewrite_href(match.group(2), depth=depth)
        return stash(
            f'<img alt="{escape(match.group(1), quote=True)}" '
            f'src="{escape(href, quote=True)}">'
        )

    text = _IMAGE.sub(on_image, text)

    def on_link(match: re.Match[str]) -> str:
        href = rewrite_href(match.group(2), depth=depth)
        label = render_inline(match.group(1), depth=depth)
        return stash(f'<a href="{escape(href, quote=True)}">{label}</a>')

    text = _LINK.sub(on_link, text)

    def on_bold(match: re.Match[str]) -> str:
        return stash(f"<strong>{restore(escape(match.group(1)))}</strong>")

    text = _BOLD.sub(on_bold, text)

    def on_em(match: re.Match[str]) -> str:
        return stash(f"<em>{restore(escape(match.group(1)))}</em>")

    text = _EM.sub(on_em, text)
    return restore(escape(text))


def rewrite_href(href: str, *, depth: int) -> str:
    href = href.strip()
    if href.startswith(("#", "mailto:", "http://", "https://")):
        return href
    path, frag = href, ""
    if "#" in href:
        path, frag = href.split("#", 1)
        frag = "#" + frag
    name = Path(path).name
    if name in SITE_FILES:
        target = SITE_FILES[name]
        prefix = "../" * depth
        return f"{prefix}{target}{frag}"
    if path.startswith("assets/") or name.endswith((".png", ".svg", ".jpg", ".webp")):
        prefix = "../" * depth
        return f"{prefix}{path.lstrip('./')}{frag}"
    if path.endswith(".html") or path.endswith(".json"):
        if depth and not path.startswith("../"):
            return path + frag
        prefix = "../" * depth
        return f"{prefix}{path}{frag}"
    # In-repo markdown / other files → GitHub blob. The site does not fork those copies.
    if path.startswith("../"):
        rel = _norm_from_docs(path)
    elif path.startswith("docs/"):
        rel = path
    else:
        rel = f"docs/{path}"
    return f"{BLOB}/{rel}{frag}"


def _norm_from_docs(path: str) -> str:
    parts: list[str] = ["docs"]
    for part in Path(path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def write_page(
    path: Path,
    *,
    title: str,
    body: str,
    depth: int,
    current: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "../" * depth
    home = f"{prefix}index.html"
    blog = f"{prefix}blog/index.html"
    css = f"{prefix}site.css"
    home_attr = ' aria-current="page"' if current == "home" else ""
    blog_attr = ' aria-current="page"' if current == "blog" else ""
    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="dark light">\n'
        f"<title>{escape(title)}</title>\n"
        '<meta name="description" content="Antiserum: local antivirus for training data. Offline CLI, no API keys, no hosted scan.">\n'
        f'<link rel="stylesheet" href="{escape(css, quote=True)}">\n'
        "</head>\n"
        "<body>\n"
        '<a class="skip" href="#main">Skip to content</a>\n'
        "<header>\n"
        "<nav>\n"
        f'<a class="mark" href="{escape(home, quote=True)}"{home_attr}>antiserum</a>\n'
        f'<a href="{escape(home, quote=True)}">docs</a>\n'
        f'<a href="{escape(blog, quote=True)}"{blog_attr}>blog</a>\n'
        f'<a href="{escape(GITHUB, quote=True)}">github</a>\n'
        "</nav>\n"
        "</header>\n"
        '<main id="main">\n'
        f"{body}"
        "</main>\n"
        "<footer>\n"
        "<p>MIT. Local CLI. No telemetry. This site is documentation only — "
        "it does not scan, judge, or host corpora. "
        f'Source: <a href="{escape(GITHUB, quote=True)}">'
        "antiserum-ai/antiserum</a>.</p>\n"
        "</footer>\n"
        "</body>\n"
        "</html>\n"
    )
    path.write_text(html, encoding="utf-8")


def _first_heading(html: str) -> str:
    match = re.search(r"<h1>(.*?)</h1>", html, flags=re.S)
    if not match:
        return ""
    return re.sub(r"<[^>]+>", "", match.group(1)).strip()


def _date_from_name(name: str) -> str:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    return match.group(1) if match else ""


if __name__ == "__main__":
    raise SystemExit(main())
