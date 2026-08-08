# LocalPibox Stack Review — Findings & Improvement Summary

> Full audit of the 8-repo LocalPibox stack (devstack, pi, config,
> lemonade-pi-plugin, pi-subagents, lpb-memory, localpibox,
> localpibox.github.io).
> Date: 2026-08-08 · Status: **for review & decision** — nothing changed yet.

This document collects confirmed incongruences, documentation gaps, webpage
improvements, and a prioritized roadmap. Each item has a concrete fix so we can
decide and implement.

---

## Priority legend

- **P0** — broken, wrong, or a real risk; fix first.
- **P1** — drift/stale content or clear quality gap; fix soon.
- **P2** — polish / enhancement; do when convenient.

---

## 1. Security (P0)

### 1.1 Leaked GitHub token in git remote URL
- **Where:** `devstack/.git/config:8` — an embedded `gho_` OAuth token in the
  fetch/push URL. **Status: resolved** — removed from the remote on 2026-08-08;
  token was not in committed files or `backup/` tarballs, so history is clean.
  **User action still required:** revoke the leaked `gho_` token instance in
  GitHub → Settings → Applications / token settings (rotation is a manual step
  I cannot do for you).
- **Risk:** anyone with repo read access or a dump of the working dir can push
  to this account.
- **Fix:**
  1. ✅ Removed from the remote URL on 2026-08-08.
  2. ✅ Verified absent from committed files and `backup/` tarballs (grep) — no
     history scrub required.
  3. ⏳ User: revoke/rotate the leaked `gho_` token instance in GitHub settings.
- **Also check:** the other repos' remotes were clean (no token), but re-verify
  after rotation.

### 1.2 Stray draft file in repo root
- `devstack/GH-PROFILE-DRAFT.md` — a GitHub-profile bio draft for the user,
  committed to the repo root. This is task debris, not project documentation.
- **Fix:** move to personal notes (or delete). It doesn't belong in the stack
  repo.

---

## 2. Broken links & missing files (P0)

### 2.1 `CONTRIBUTING.md` does not exist in **any** repo
- **Linked to but missing in:** `devstack`, `config`. Referenced by:
  - `localpibox.github.io/index.html` (2×: "Docs & guides" + "Contributing")
  - `localpibox/README.md` (3×)
  - `config/README.md:105`
  - `devstack/README.md` (multiple "See .../CONTRIBUTING.md")
- **Fix:** write a real `devstack/CONTRIBUTING.md` (three contribution paths are
  already described in the README — promote that content), and add a short
  `config/CONTRIBUTING.md` or repoint config links to devstack's.
- **Note:** `lemonade-pi-plugin/CONTRIBUTING.md` and `lpb-memory/CONTRIBUTING.md`
  already exist and are fine.

### 2.2 `config/VERSION` missing, but CI and docs depend on it
- `devstack/.github/workflows/build-and-publish.yml:98,168` read
  `raw.githubusercontent.com/$CONFIG_FORK/$CONFIG_REF/VERSION` to compute the
  image version tag. The config repo has **no VERSION file**, so images get
  tagged `...:unknown-cli` / `...:unknown-web`.
- `doc/BRANCH-STRATEGY.md:9,34` declares `config/VERSION` the "source of truth".
- **Fix:** add `config/VERSION` = `0.2.0-lpb` (see version alignment in §4).

### 2.3 Repo rename `pi-hermes-memory` → `lpb-memory` not propagated
The `localpibox/pi-hermes-memory` repo returns **404**. Old name still used in:
- `devstack/README.md:404` (Related Repositories)
- `devstack/Dockerfile:16` (comment) and `Dockerfile:141`
  (`hermes-memory-config.json` path)
- `devstack/support/validate.sh:126`
- `devstack/doc/ARCHITECTURE.md:58`, `doc/BRANCH-ANALYSIS.md` (4×),
  `doc/BRANCH-STRATEGY.md:36,62`

**Fix:** rename all these to `lpb-memory` / `lpb-memory-config.json`.

### 2.4 `hermes-memory-config.json` → `lpb-memory-config.json` rename (same rename)
- Still old: `devstack/Dockerfile:141`, `devstack/doc/config-utility.md:11`.
- Already correct: `support/start.sh:258`, `config/README.md`, `config/` tree.
- **Fix:** update the two stale files. This would otherwise ship a broken
  `cp` in the Docker build.

---

## 3. Documentation drift / stale content (P0–P1)

### 3.1 Version drift across repos
| File | Value |
|---|---|
| `devstack/VERSION` | `0.1.0-lpb` |
| `devstack/lpb.conf.env:66` (`LPB_VERSION`) | `0.2.0-lpb` |
| `lpb-memory/VERSION` | `0.2.0-lpb` |
| `lemonade-pi-plugin/VERSION` | `0.2.0-lpb` |

**Fix:** align everything to **`0.2.0-lpb`** (bump `devstack/VERSION`; confirm
`config/VERSION` matches).

### 3.2 `config/README.md` package list vs `settings.json`
- README `:62` says `lemonade-pi-plugin@patches/api-key-auth`; `settings.json`
  uses `@lpb`.
- README `:64` says `npm:@tintinweb/pi-subagents`; `settings.json` uses
  `git:.../pi-subagents@lpb`.
- Actual `settings.json` packages (5): `lemonade-pi-plugin@lpb`,
  `lpb-memory@main`, `npm:pi-mcp-adapter`, `pi-subagents@lpb`,
  `npm:pi-powerline-footer`.
- **Fix:** align README package strings with `settings.json`.

### 3.3 `config/VALIDATION.md` is stale
- Reports `hermes-memory-config.json` as "missing from README" and claims 6
  packages. Reality: file is `lpb-memory-config.json` and 5 packages.
- **Fix:** refresh to match current `config/` state.

### 3.4 Branch-name inconsistency (claim vs reality)
- `doc/BRANCH-STRATEGY.md:7` claims "`lpb` branch on all 5 repositories" — false.
- **Actual default branches:**
  | Repo | Default | Kind |
  |---|---|---|
  | devstack | `main` | own |
  | config | `main` | own |
  | localpibox | `main` | own |
  | localpibox.github.io | `main` | own |
  | lpb-memory | `main` | own/independent |
  | pi | `lpb` | fork |
  | lemonade-pi-plugin | `lpb` | fork |
  | pi-subagents | `master` (has `lpb`) | fork → uses `lpb` for the patch |
- **Fix:** correct `BRANCH-STRATEGY.md` to describe the real convention:
  *own/independent repos → `main`; forks → `lpb`* (pi-subagents has an `lpb`
  branch with the patch, even though upstream default is `master`). Optionally
  set `pi-subagents` default branch to `lpb` to remove the `@lpb` vs default
  mismatch.

### 3.5 `support/start.sh` described as "legacy/superseded"
- `README.md` Directory Structure calls `support/start.sh` "Legacy entrypoint
  (superseded by entrypoint-*)", but it is 29 KB and actively maintained
  (recent commits 428e576→937ce1e). It's the runtime env/validation layer, not
  dead code.
- **Fix:** correct the README description to reflect its real role (runtime
  config, validation, browser-agent setup).

---

## 4. Webpage improvements — `localpibox.github.io`

The live site matches the source (`index.html`, single self-contained file,
~7 KB, deploy via `pages.yml`). It's fast and technically clean; gaps below.

### 4.1 Repo table accuracy (P0)
- **"The stack" lists 6 repos; there are 8.** Omit `localpibox` (canonical
  overview, already linked elsewhere) and `localpibox.github.io` (this site).
  Add them as `own` rows.
- **Fix 2 misleading descriptions:**
  - `pi-subagents` → "Claude Code–like subagents: parallel execution, live
    widget, custom agent types, mid-run steering" (not just "registry").
  - `devstack` → "container image + `lpb` launcher + **VSCodium web IDE**, CI,
    bootstrap" (it omits `--web`, a core feature).

### 4.2 SEO / metadata (P0)
- Add `rel="canonical" href="https://localpibox.github.io/"`.
- Add **Open Graph + Twitter Card**: `og:title/description/url/type/site_name`,
  `twitter:card=summary`, `og:image`. (No social preview today.)
- Add **JSON-LD**: `SoftwareApplication` + `WebSite`/`Organization`.
- Add an **inline SVG favicon** (accent-dot motif).

### 4.3 Accessibility & UX (P1)
- Add semantic landmarks: wrap in `<main>`, use `<section id=…>` blocks with an
  in-page `<nav>` (the page is currently all `div`s with a long scroll).
- `.repo-link{color:var(--fg)}` — repo names look like plain text. Add
  underline + accent so links are visibly clickable.
- Mobile: `td:first-child{white-space:nowrap}` overflows on narrow screens
  (long names/URLs). Wrap tables in an `overflow-x:auto` container.
- Add `:focus-visible` styling for keyboard users. Existing contrast passes AA.

### 4.4 Design polish (P1–P2)
- Add a small SVG/ASCII **architecture diagram** in the hero (doubles as
  `og:image`).
- Differentiate heading type weight/scale (single `system-ui` stack uses one
  weight everywhere); add `h1` letter-spacing.
- Add a **status badge row** (Pi.dev / Lemonade / Qwen / Pages).

### 4.5 New content (P2)
- **Quick start** section (prereqs, `install.sh`, `lpb <proj>`) — currently
  install is buried under "The lpb utility".
- **Hardware/requirements** (podman/docker, RAM, APU guidance beyond the 128 GB
  example).
- **Roadmap** (seed with the already-planned `pi-config` utility).
- **License note** — all repos report `license: null` on GitHub; state it
  explicitly.

---

## 5. Other improvements / roadmap candidates

### 5.1 Repo hygiene
- `devstack/.pi/mcp.json` has an uncommitted working-tree change enabling
  `exa` (currently disabled in HEAD). Commit intentionally or revert.
- `devstack/doc/mcp-server-research.md` is an untracked new file (MCP server
  research). Decide whether to keep + commit, move to notes, or drop.
- `devstack/scripts/__pycache__/` exists (gitignored — confirm no committed
  artifacts; currently 0 tracked).
- `openspec/` dirs are empty (`specs/`, `changes/`, `changes/archive` all
  empty). Either adopt OpenSpec for future changes or remove to avoid dead
  scaffolding in the repo.

### 5.2 Tooling / workflow
- **Implement `pi-config` utility** — a fully-specified design doc exists
  (`devstack/doc/config-utility.md`) but no implementation. It's the natural
  "next feature".
- **MCP server research** (`doc/mcp-server-research.md`) covers context7, etc.
  Decide whether to add context7 (or `docs-mcp-server`) to the stack for
  real-time API docs.
- **Browser validation pipeline** (`browser-validate.ts`, schemas) — already
  built; consider wiring into CI as a smoke test rather than run manually.

### 5.3 Process / consistency
- The `lpb-memory` and `pi-subagents` READMEs reference
  `config-utility.md`/workflow that doesn't exist consistently — re-review the
  few spots touched by the rename to confirm no "planned" doc blocks remain.
- The github.io page's `#anchor` links (e.g. `#architecture`,
  `#forking--repointing`) should be spot-checked after edits.

---

## 6. Recommended decision order

| Phase | Works |
|---|---|
| **1 — Security (urgent)** | rotate token, scrub remote/history, remove GH-PROFILE-DRAFT |
| **2 — Fix P0 links/files** | write CONTRIBUTING.md, add config/VERSION, propagate `lpb-memory` rename (README/Dockerfile/validate.sh/docs) |
| **3 — Align versions & docs** | bump devstack/VERSION→0.2.0, fix BRANCH-STRATEGY, refresh config README/VALIDATION, fix start.sh description |
| **4 — Webpage refresh** | repo table (8), SEO/OG/JSON-LD/favicon, accessibility, hero, quick-start/roadmap sections, push to `localpibox.github.io` |
| **5 — Rollup** | commit `.pi/mcp.json` + research doc intentionally, tidy openspec, scope `pi-config`/MCP additions |

---

## Appendix — files touched by the `pi-hermes-memory` rename (checklist)

- [ ] `devstack/README.md:404`
- [ ] `devstack/Dockerfile:16,141`
- [ ] `devstack/support/validate.sh:126`
- [ ] `devstack/doc/ARCHITECTURE.md:58`
- [ ] `devstack/doc/BRANCH-ANALYSIS.md` (90,137,152,163,171)
- [ ] `devstack/doc/BRANCH-STRATEGY.md:36,62`
- [ ] `devstack/doc/config-utility.md:11`
