# Design: Manual Tagging & lpb-config Split

**Status:** Implemented (2026-08-20) — see Implementation Notes below
**Date:** 2026-08-20

---

## Part 1: CI Changes — VERSION-Driven Pipeline

### How It Works

CI runs on **every push** to dev/main (path-filtered to code changes). A new **`VERSION_CHECK`** job determines whether the commit changed VERSION:

```yaml
Phase 0: VERSION_CHECK  — Did this commit change devstack/VERSION?
Phase 1: test-lpb      — Always runs (fast validation)
Phase 2: build-cli      — Only if VERSION changed
Phase 3: build-web      — Only if VERSION changed
Phase 4: tag-repos      — Only if VERSION changed
Phase 5: status         — Always runs (depends on build* results)
```

**`VERSION_CHECK`** reads the commit diff:
```bash
git diff-tree --no-commit-id --name-only -r "$GITHUB_SHA" | grep -q "VERSION"
```

- **VERSION changed** → triggers `build-cli`, `build-web`, `tag-repos`
- **No VERSION change** → skips build/tag, only runs tests
- **No code change** (only VERSION bump) → excluded by `paths` filter, no re-trigger

### Key Changes to CI Jobs

| Job | Current | New |
|---|---|---|
| `bump-version` | Auto-increment + commit + push | **Removed** |
| `build-cli` / `build-web` | `needs: [bump-version]` → reads output | `needs: [test-lpb]` + `if: needs.VERSION_CHECK.outputs.changed == 'true'` → reads VERSION file directly |
| `tag-repos` | `needs: [build-*]` → reads bump-version output | Same needs → reads VERSION file directly |

### Version Reading in Build Jobs

**Old:** `LPB_VERSION=${{ needs.bump-version.outputs.version }}`
**New:** Read VERSION from the repo in each build step:
```bash
echo "LPB_VERSION=$(cat VERSION)" >> "$GITHUB_OUTPUT"
```

### CI Image Tagging (unchanged)

| Trigger | Image tags |
|---|---|
| Push to `dev` (VERSION changed) | `:{v}-cli`, `:{v}-web`, `:dev-cli`, `:dev-web`, `:{sha}-cli`, `:{sha}-web` |
| Push to `main` (VERSION changed) | `:{v}-cli`, `:{v}-web`, `:main-cli`, `:main-web`, `:latest-cli`, `:latest-web`, `:{sha}-cli`, `:{sha}-web` |
| Weekly cron | `:weekly-cli`, `:weekly-web` |
| Manual `release=true` | `:latest-cli/web` (override) |

---

## Part 2: Tool Split

### `lpb-config` — Config Repo Manager Only

**Location:** `devstack/support/lpb-config` (installed to `/opt/pi-support/lpb-config`)
**Purpose:** Ship inside Docker image. Manage the config repo (`~/.pi/agent/`) that lives on the host volume.

**Commands (minimal ~250 lines):**

```
lpb-config status          — Config repo HEAD, remote, local changes
lpb-config update          — Fetch + fast-forward config repo (safe)
lpb-config reset [--force] — Re-clone config repo (destructive)
lpb-config merge           — Interactive git merge for config repo
lpb-config align           — Sync extension pins to latest GitHub tags

lpb-config memory show     — Show lpb-memory config
lpb-config memory setup    — Interactive memory config wizard

# Pipeline detection still needed (for --tag on memory/align)
```

**What's removed from lpb-config:**
- ❌ `workspace` subcommand (branch switching, repo syncing)
- ❌ `validate` (full stack alignment check)
- ❌ `release` (stable promotion across repos)

### `lpb-devstack` — DevOps Workspace Tool

**Location:** `devstack/scripts/lpb-devstack` (installed to `/opt/pi-support/lpb-devstack`)
**Purpose:** Available in the workspace, for developers working on the stack.

**Commands:**

```
# VERSION bumping
lpb-devstack bump                    # bump patch (0.0.57 → 0.0.58-lpb-dev)
lpb-devstack bump --minor            # bump minor
lpb-devstack bump --major            # bump major
lpb-devstack bump --set 0.1.0-lpb-dev  # explicit version

# Repo tagging
lpb-devstack tag-repos               # tag 5 repos with committed VERSION
lpb-devstack tag-repos --branch dev  # tag on dev branches
lpb-devstack tag-repos --branch main # tag on main branches
lpb-devstack tag-repos --version v   # explicit version

# Workspace management
lpb-devstack workspace status        — branches + alignment
lpb-devstack workspace sync          — clone/symlink/align/pull
lpb-devstack workspace sync --extensions — sync settings.json pins
lpb-devstack workspace ensure [--fix] — switch to correct branches

# Stack validation
lpb-devstack validate                — full stack alignment check

# Release promotion
lpb-devstack release status          — readiness across 6 repos
lpb-devstack release promote         — dev→stable merge + push

# Pre-commit validation
lpb-devstack validate-hooks          — run full pre-commit checks (tests + validation)
```

### Tool Scope Decision Matrix

| Feature | `lpb-config` | `lpb-devstack` | Reason |
|---|:---:|:---:|---|
| Config repo management | ✅ | ❌ | Ships in image, needed inside container |
| Extension pin alignment | ✅ | ❌ | Cross-repo, image-usable |
| Memory config | ✅ | ❌ | Image-usable, needed inside container |
| VERSION bumping | ❌ | ✅ | Devstack-specific, workspace tool |
| Tag repos | ❌ | ✅ | Dev-time operation |
| Workspace sync/ensure | ❌ | ✅ | Developer workspace maintenance |
| Stack validation | ❌ | ✅ | Dev-time operation |
| Release promote | ❌ | ✅ | Dev→stable promotion |
| Pre-commit validation | ❌ | ✅ | Dev-time operation |

### File Locations

```
devstack/
├── support/
│   ├── lpb-config          ← slimmed down (config repo only, ~250 lines)
│   └── lpb-devstack        ← new (devops, ~600 lines)
├── scripts/
│   ├── lpb-config          ← symlink → ../support/lpb-config
│   ├── lpb-devstack        ← symlink → ../support/lpb-devstack
│   ├── localpibox/
│   │   ├── _stack_lib.py   ← shared code (git, repo defs, pipeline detection)
│   │   └── ...
│   └── install.sh          ← install both scripts
└── .githooks/
    └── pre-commit          ← keep full check (tests included)
```

---

## Part 3: Pre-commit — Keep Full Check

The pre-commit hook runs the full `test_lpb.py` suite. This is **intentional** — it's a safeguard against AI-generated garbage reaching the repository. The 1-2 second cost is worth the protection.

**No changes to pre-commit** — keep as-is with test execution.

---

## Implementation Order

1. **Create `scripts/localpibox/_stack_lib.py`** — extract shared code from lpb-config
2. **Slim `support/lpb-config.py`** — remove workspace/release/validate, keep config repo + memory
3. **Create `support/lpb-devstack`** — new CLI with bump, tag-repos, workspace, release
4. **Update CI (`build-and-publish.yml`)** — add VERSION_CHECK, remove bump-version, read VERSION directly
5. **Update `.githooks/pre-commit`** — no changes (keep full check)
6. **Update documentation** — split docs, update SKILL.md
7. **Update `scripts/install.sh`** — install both scripts

---

## Implementation Notes (2026-08-20)

Implemented as approved, with these deviations (each preserves the design's
intent):

1. **VERSION is in the CI `paths` filter** (not excluded). The doc bullet
   "No code change (VERSION-only bump) → excluded by paths filter" would
   have made a plain `lpb-devstack bump` + push a CI no-op, defeating the
   manual-tagging flow. A VERSION-only push IS the release trigger:
   `VERSION_CHECK` reports changed → build + tag run. Code-only pushes still
   run tests only. (`lbp.stack.env`/`lpb.conf.env` remain excluded — they
   ship with the next bump.)

2. **Cron / manual dispatch always build.** `VERSION_CHECK` outputs
   `changed=true` for `schedule` and `workflow_dispatch` events, preserving
   the weekly-cron and on-demand `:latest` behavior from the doc's
   "CI Image Tagging (unchanged)" table.

3. **`_stack_lib.py` holds the full stack-operation implementations**
   (workspace/validate/release command functions), not just git primitives
   and repo definitions. Both CLIs stay thin (`lpb-config` ≈ 500 lines,
   `lpb-devstack` ≈ 400), and the test suite has one patch target for all
   stack state. The doc's line estimates (250/600) were pre-command-list.

4. **`support/lpb-config.py` → `support/lpb-config`** (extensionless, per the
   file tree). The test harness loads extensionless scripts via
   `importlib.machinery.SourceFileLoader`. The Dockerfile COPY/symlinks and
   `install.sh` were updated to match.

5. **`lpb-devstack tag-repos` tags through the local workspace clones**
   (fetch branch → push tag ref) instead of the GitHub API: no raw-SHA push
   works without the objects in a local ODB, and the workspace is the tool's
   home turf. Missing clone → clear error pointing at `workspace sync`.
   CI's `tag-repos` job keeps the API approach (no workspace there).

6. **`VERSION_CHECK` handles merge commits** — `git diff-tree` shows nothing
   for merges by default, so it falls back to diffing against the first
   parent.

7. Fixed a latent bug in the stack-env lookup while moving it:
   `Path("/opt/devstack/lpb.stack.") / f"{pipeline}.env"` built a bogus
   path; now `Path("/opt/devstack") / f"lpb.stack.{pipeline}.env"`.
