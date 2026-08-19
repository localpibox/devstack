# Docs branch

This branch carries the documentation site for the LocalPibox stack
(MkDocs Material + [mike](https://github.com/jimporter/mike)).

- **Content lives in place** — `README.md`, `doc/`, `support/docs/`,
  `.pi/skills/...` are the same files as on `dev`. Keep this branch merged
  with `dev` so hand-written docs never drift.
- **`docs/` is derived** (gitignored) — `scripts/generate.py` copies the
  tracked content and stamps version pages (repo map, versions) from the
  6 stack repos. Run it before every build; CI does this automatically.
- **Mermaid diagrams** (` ```mermaid ` fences, e.g. in `README.md`) are
  rendered client-side by the Material theme, which lazy-loads mermaid@11
  from the unpkg CDN on first visit — viewing diagrams needs internet
  access; without it the raw source shows as a code block (fallback).
- **Versions** are cut by `.github/workflows/docs-publish.yml`:
  - push to `docs` → living `edge` version (always newest content)
  - dispatch with `tag: 0.0.X-lpb[-dev]` → immutable per-tag version + alias
    (`latest` = stable, `dev` = dev pipeline)
  - root of the site redirects to `latest` (or `edge` until the first tag)
  - served from the `gh-pages` branch (mike's branch) by GitHub Pages

## Local build

```bash
python3 -m pip install --user "mkdocs-material==9.7.7" mike
python3 scripts/generate.py          # or: --tag 0.0.53-lpb-dev
mike serve                           # live preview at http://localhost:8000
```

## Cutting a version (after a code release)

1. Merge `dev` into `docs` (content up to date), push.
2. Cut the version. The `docs` workflow's `workflow_dispatch` is unreachable
   from the GitHub UI/API (the workflow file only exists on the `docs`
   branch, and dispatch resolves from the default branch `dev`) — so cut it
   locally with mike (this is exactly what the workflow does):

   ```bash
   git checkout docs && git pull
   git config user.name lpb-docs && git config user.email ci@lpb-stack.dev
   python3 scripts/generate.py --tag 0.0.X-lpb[-dev]
   mike deploy 0.0.X-lpb[-dev] latest --push --update-aliases   # stable
   # (or: alias dev for a dev-pipeline tag, no stable release yet)
   mike set-default latest --push
   ```

   If mike reports `gh-pages has diverged`, the local branch is stale from
   an earlier local session — reset it: `git fetch origin gh-pages &&
   git update-ref refs/heads/gh-pages origin/gh-pages`.
3. Result: `https://lpb-stack.github.io/devstack/0.0.X-lpb[-dev]/` and the
   alias (`latest` = stable, `dev` = dev pipeline) points at it.

Note: while no fully-aligned stable release exists, cut the newest
`*-lpb-dev` tag with alias `latest` so the root serves the newest docs;
re-cut with the first `0.0.X-lpb` stable tag when it ships.
