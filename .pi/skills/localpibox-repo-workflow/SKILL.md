---
name: lpb-stack-repo-workflow
description: Manage the 6 LocalPibox repos — CI-only versioning, stable releases, image builds, lpb.py.
---
# LocalPibox Repository Workflow

Versioning model: **single-source** (devstack/VERSION). CI bumps the version
after tests pass, commits it to the pushed branch, tags the other 5 repos,
and builds images. Git hooks validate only — no cross-repo writes, no
local version bumping.

## When to Use

- Onboarding new developers to the LocalPibox stack
- Setting up or debugging CI/CD (build-and-publish.yml)
- Creating the stable (main) release from dev
- Debugging version/tag/pin alignment issues
- Adding/removing repos from the stack
- Validating Docker image builds for `dev` or `main` targets
- Using `lpb --version`, `lpb --tag`, `lpb.py`, `lpb-config`

## Versioning Model (Option C)

```
Single source: devstack/VERSION
CI: tests pass → bump patch (branch-aware suffix) → commit to pushed branch
    → tag other 5 repos → build + publish images
```

- **devstack/VERSION** — the only VERSION file in the stack (e.g. `0.0.46-lpb-dev`)
- **Format:** dev pipeline `0.0.x-lpb-dev`, main pipeline `0.0.x-lpb`
- **CI bump** preserves major.minor, increments patch, appends `-dev` only on dev
- **Tags** — created by CI on the **other 5 repos only** (devstack is tracked by
  its VERSION file, never tagged), pointing at the pipeline's branch HEAD
- **`lpb.stack.env`** — `LPB_PI_REF` / `LPB_CONFIG_REF` are **branch names**
  (`lpb-dev`/`lpb`, `dev`/`main`), never versions
- **Pipeline profiles** — `lpb.stack.dev.env` / `lpb.stack.main.env` override the
  refs per pipeline (`lpb --tag dev|main`)
- **Docker images** — `ghcr.io/lpb-stack/devstack` tagged per pipeline (see CI/CD)
- **package.json** — keeps original fork versions, CI never touches it

## Repository Map

| Repo | Type | dev branch | stable branch |
|---|---|---|---|
| **devstack** | workspace (single source) | `dev` | `main` |
| **config** | workspace (agent preset) | `dev` | `main` |
| **lpb-memory** | workspace + extension | `dev` | `main` |
| **pi** | workspace (CI clones to /opt/pi-src) | `lpb-dev` | `lpb` |
| **pi-subagents** | extension | `lpb-dev` | `lpb` |
| **lemonade-pi-plugin** | extension | `lpb-dev` | `lpb` |

Org: all repos live under **`github.com/lpb-stack`** (migrated from
`localpibox` in Aug 2026). Note: **`localpibox` remains the project name and
the Python package name** (`scripts/localpibox/`, `import localpibox`); only
the GitHub org and GHCR paths use `lpb-stack`.

## Repository Layout

```
Workspace:
  /home/lpb/workspace/devstack            (real clone, single source)
  /home/lpb/workspace/pi                  (real clone, lpb-dev/lpb)
  /home/lpb/workspace/pi-subagents        (symlink → agent git clone)
  /home/lpb/workspace/lemonade-pi-plugin  (symlink → agent git clone)
  /home/lpb/workspace/lpb-memory          (symlink → agent git clone)

Agent config (cloned from lpb-stack/config by start.sh at container start):
  /home/lpb/.pi/agent/                    (settings.json, AGENTS.md, skills/, agents/)

Extension clones (pi loads these per settings.json pins):
  /home/lpb/.pi/agent/git/github.com/lpb-stack/
      lemonade-pi-plugin, lpb-memory, pi-subagents

⚠️ Extensions update at runtime via `pi update --extensions`.
   They are NOT baked into Docker images.
   CI clones pi into /opt/pi-src during the Docker build; workspace/pi is
   for local development only.
```

## Branch Strategy

- **`dev`** (devstack, config, lpb-memory): primary development. Default on GitHub.
- **`main`** (devstack, config, lpb-memory): stable release branch.
- **`lpb-dev`** (pi, pi-subagents, lemonade-pi-plugin): active development from
  upstream + LPB patches. Default on GitHub.
- **`lpb`** (pi, pi-subagents, lemonade-pi-plugin): stable branch — receives
  clean merges from `lpb-dev` via the release procedure. Divergence from
  `lpb-dev` is normal during active development.

**Rule:** always work on the default branch (`dev` or `lpb-dev`).

## Commit Author Convention

The only available identity is:

```
localpibox <localpibox@gmail.com>
```

CI commits use `ci-localpibox <ci@lpb-stack.dev>`.

## Stable Release Procedure (dev → main)

There is no local version script — **`lpb-config release` is the tool**
(`support/version.sh` was removed as dead code).

```bash
# 1. Readiness check (all 6 repos, non-destructive, fetches first)
lpb-config release status

# 2. Inspect the exact plan without changing anything
lpb-config release promote --dry-run

# 3. Promote (interactive confirmation)
lpb-config release promote
```

What promote does per repo:
- **ff / clean 3-way:** resets local stable branch to `origin/<stable>`,
  merges `origin/<dev>`, pushes
- **unrelated histories** (re-initialized stable branch, first release):
  requires explicit `--rebase` — replaces the stable branch with the dev
  history and force-pushes (`git push --force-with-lease`)
- **conflict:** leaves the repo untouched, reports it
- **dirty local repo:** skipped, reported
- **local stable branch ahead of origin** (unpushed commits): skipped with
  guidance — delete the local branch (`git branch -D <stable>`, only with
  explicit user confirmation) and re-run
- **devstack only:** strips the `-dev` VERSION suffix on `main` and commits
  it (e.g. `0.0.46-lpb-dev` → `0.0.46-lpb`)

After promote, CI (main pipeline) finishes the release:
1. Bumps VERSION to `0.0.(x+1)-lpb` on `main`
2. Tags the 5 repos on their stable branches (`lpb`/`main`)
3. Builds `:{v}-cli/web`, `:main-cli/web`, `:latest-cli/web`, `:{sha}-cli/web`

Then align the runtime to the stable pipeline:
```bash
lpb-config --tag main workspace sync --extensions   # pins → stable tag
pi update --extensions
lpb --tag main validate                            # or lpb-config --tag main validate
```

Flags: `--yes` (skip confirmation), `--dry-run` (plan only), `--rebase`
(first-release mode for unrelated histories). Re-runs are safe: promoted
repos fast-forward or no-op.

## Stack Validation & Sync (lpb-config)

**`lpb-config`** — single tool for config repo, workspace, and validation:

```bash
lpb-config validate                     # Validate entire stack alignment
lpb-config workspace status             # Show branches + alignment
lpb-config workspace sync               # Symlinks + git pull current branches
lpb-config workspace sync --extensions  # Sync settings.json pins to stack version
lpb-config workspace ensure [--fix]     # Check/fix branch alignment for pipeline
lpb-config status | update | reset      # Config repo management
lpb-config align                        # Update extension pins to latest GitHub tags
lpb-config memory show | setup          # lpb-memory extension config wizard
lpb-config release status | promote     # Stable release (see above)

# Pipeline override (dev vs main) on any command:
lpb-config --tag main validate
```

## Settings.json Lifecycle

**Template-driven generation**, not git-tracked:

1. Config repo ships `settings.json.template` with `__LPB_VERSION__` placeholders
2. First boot: `start.sh` generates `settings.json` (replaces placeholders)
3. No model/provider preconfigured — user runs `/login lemonade`
4. Pin sync: `lpb-config workspace sync --extensions`
   (main pipeline reads the stable version from devstack `origin/main`)
5. `lpb-config validate` checks pins match the current stack version
6. Persistent on the host volume — survives container rebuilds

Pins look like: `git:github.com/lpb-stack/pi-subagents@0.0.46-lpb-dev`

## lpb-memory Config Lifecycle

Same pattern — template in config repo, user config on host volume:

1. First boot: `start.sh` copies `lpb-memory-config.json.template` → config
2. No model override — uses the main model until the user configures
3. Tune: `lpb-config memory setup` (interactive wizard)
4. Review: `lpb-config memory show`

## Hooks (devstack only, `core.hooksPath=.githooks`)

**pre-commit** — validates BEFORE commit (exit non-zero aborts):
1. VERSION format (`0.x.y-lpb[-dev]`)
2. `lpb.stack.env` `LPB_PI_REF` is a branch name (`lpb` or `lpb-dev`)
3. settings.json extension pins match VERSION (warn-level)
4. Working tree clean (except VERSION/env/hooks changes)
5. `scripts/test_lpb.py` passes (skip with `SKIP_TESTS=1 --no-verify`)

**commit-msg** — **no-op.** Version bumping is CI's job (bump-version job
after tests pass). Git hooks never write VERSION or cross-repo state.
`.github/scripts/commit-msg-auto-version` was removed (dead code from the
old cross-repo bump model).

## CI/CD Workflow

`.github/workflows/build-and-publish.yml` (org: `lpb-stack`):

Triggers (no tag triggers — push-to-branch only):
- push to `dev` or `main` (paths: Dockerfile, support/**, scripts/**, workflow)
  — VERSION/lpb.stack.env changes are excluded to avoid re-triggering on auto-bumps
- pull_request to `main` (tests only, no builds/pushes)
- weekly cron (Monday 03:00 UTC) → `:weekly-cli/web`
- manual dispatch (`publish_latest`, `no_cache` inputs)

Jobs:
1. **test-lpb** — `scripts/test_lpb.py` + `scripts/test_localpibox.py`
2. **bump-version** — bump patch (preserves major.minor, `-dev` suffix on dev),
   commit + push to the **pushed branch** (`${GITHUB_REF_NAME}`)
3. **build-cli / build-web** — publish per pipeline:
   - dev push: `:{v}-cli/web`, `:dev-cli/web`, `:{sha}-cli/web`
   - main push: `:{v}-cli/web`, `:main-cli/web`, `:latest-cli/web`, `:{sha}-cli/web`
   - manual with `publish_latest`: `:latest-cli/web`
4. **tag-repos** — after successful builds: tags the 5 repos on the pipeline's
   branches (dev: `lpb-dev`/`dev`, main: `lpb`/`main`) using `LPB_STACK_PAT`.
   Retries transient 5xx with backoff and **fails the run if any repo's tag
   fails** (a partially-tagged stack is a release bug — re-running the job is
   idempotent, 422 = already tagged). A missing branch aborts immediately.

Images: `ghcr.io/lpb-stack/devstack` in two flavours per tag — `…-cli`
(base dev env + Pi CLI) and `…-web` (extends cli + VSCodium server). The bare
`:cli`/`:web` tags do NOT exist — CI only publishes versioned plus
`:dev-*`/`:main-*`/`:latest-*`/`:sha-*` (pulling a bare tag fails with
`manifest unknown`).

CI does NOT use `workspace/pi` — it clones pi from `LPB_PI_FORK`
(`lpb-stack/pi`) into `/opt/pi-src` during the Docker build.

## lpb Launcher

- `scripts/lpb` (wrapper) → `scripts/lpb.py` (engine, stdlib-only)
- Shared helpers: `scripts/localpibox/` Python package (env/log/run/cli)
- Installed via `scripts/install.sh` (fetches from the `main` branch —
  so `main` must stay a working stable tree)
- `lpb --tag dev|main|{version}` selects the image tag; `LPB_*` vars from
  `~/.lpb-stack/devstack/` config + `lpb.stack.env`/`lpb.conf.env`

## Creating lpb-dev with an upstream base

```bash
cd /path/to/repo
git remote add upstream <upstream-url> 2>/dev/null; git fetch upstream
git checkout -b lpb-dev <upstream-tag>      # e.g. v0.84.2
git cherry-pick <lpb-commits>...            # or merge, keeping history clean
git branch -f lpb lpb-dev                   # (or keep lpb behind until stable)
git push origin lpb-dev
git push origin lpb --force-with-lease      # explicit user confirmation required
gh api repos/lpb-stack/<repo> --method PATCH -f default_branch=lpb-dev
```

## Cleanup Checklist

Before declaring a repo clean:
- [ ] Default branch set correctly (`dev` or `lpb-dev`)
- [ ] Working on the default branch
- [ ] All commits authored `localpibox <localpibox@gmail.com>` (CI: `ci-localpibox`)
- [ ] Stale branches deleted (explicit user confirmation for main/dev)
- [ ] Remote under `github.com/lpb-stack` (org migrated Aug 2026)
- [ ] `lpb` stable branch exists (receives the release promote when stable)
- [ ] pre-commit hook active (devstack: `core.hooksPath=.githooks`)
- [ ] No stale org references (`github.com/localpibox`, `ghcr.io/localpibox`)
- [ ] `lpb-config validate` passes
