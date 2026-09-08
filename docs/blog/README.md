# Blog / Updates

Dated Markdown posts for the public Pages site.

## Add a weekly post

1. Copy the newest `YYYY-MM-DD-slug.md` in this folder.
2. Rename it to today's date and a short slug.
3. Set front matter:

   ```markdown
   ---
   title: Short, technical title
   date: YYYY-MM-DD
   ---
   ```

4. Summarize what actually shipped. Quote [CHANGELOG.md](../../CHANGELOG.md), [feed/CHANGELOG.md](../../feed/CHANGELOG.md), and [field-hunt.md](../field-hunt.md). Do not invent CLI flags.
5. Preview: `make pages` then `python3 -m http.server --directory build/pages 8080`.
6. Open a PR. The `pages` workflow rebuilds `blog/index.html` newest-first on `main`.

This folder is documentation. The site does not host scans, judges, or corpora.
