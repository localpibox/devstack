# Docs branch

This branch carries the documentation site for the LocalPibox stack
(MkDocs Material + [mike](https://github.com/jimporter/mike)).

- **Content lives in place** — `README.md`, `doc/`, `support/docs/`,
  `.pi/skills/...` are the same files as on `dev`. Keep this branch merged
  with `dev` so hand-written docs never drift.
- **`docs/` is derived** (gitignored) — `scripts/generate.py` copies the
  tracked content and stamps version pages (repo map, versions) from the
  6 stack repos. Run it before every build; CI does this automatically.
- **Versions** are cut by `.github/workflows/docs-publish.yml`:
  - push to `docs` → living `edge` version (always newest content)
  - dispatch with `tag: 0.0.X-lpb[-dev]` → immutable per-tag version + alias
    (`latest` = stable, `dev` = dev pipeline)
  - root of the site redirects to `latest` (or `edge` until the first tag)
  - served from the `gh-pages` branch (mike's branch) by GitHub Pages

## Local build

```bash
python3 -m pip install --user mkdocs-material mike
python3 scripts/generate.py          # or: --tag 0.0.53-lpb-dev
mike serve                           # live preview at http://localhost:8000
```

## Cutting a version (after a code release)

1. Merge `dev` into `docs` (content up to date), push.
2. GitHub → Actions → **docs** → Run workflow → `tag: 0.0.X-lpb[-dev]`,
   `alias: latest` (stable) or `dev` (dev pipeline).
3. Result: `https://lpb-stack.github.io/devstack/0.0.X-lpb[-dev]/`
