# lpb-devstack Reference

`lpb-devstack` is the **DevOps workspace tool** for the LocalPibox stack —
for developers working on the stack (workspace + GitHub). It covers
VERSION bumping, repo tagging, workspace maintenance, full-stack
validation, and stable-release promotion.

Installed in the devstack container as `~/.local/bin/lpb-devstack`
(`podman exec -it lpb-stack lpb-devstack …`) and via `install.sh` on the
host (see [lpb CLI reference](lpb-cli.md)).

Config repo management inside the container (`status` / `update` / `reset` /
`merge` / `align` / `memory`) lives in **`lpb-config`** — see
[lpb-config reference](lpb-config.md).

## Commands

### VERSION Bumping

| Command | Description |
|---|---|
| `lpb-devstack bump` | Bump patch (`0.0.57-lpb-dev` → `0.0.58-lpb-dev`), commit |
| `lpb-devstack bump --minor` | Bump minor (`0.0.9` → `0.1.0`), commit |
| `lpb-devstack bump --major` | Bump major, commit |
| `lpb-devstack bump --set 0.1.0-lpb-dev` | Explicit version |
| `lpb-devstack bump --no-commit` | Write VERSION but don't commit |
| `lpb-devstack bump --push` | Commit **and** push (triggers the CI build + tag) |

The suffix is preserved: on `dev` you bump `0.0.x-lpb-dev`, on `main`
`0.0.x-lpb`. CI builds and tags **only when VERSION changed in the pushed
commit** — the bump commit is the release trigger.

### Repo Tagging

| Command | Description |
|---|---|
| `lpb-devstack tag-repos` | Tag the 5 stack repos (excl. devstack) at the committed VERSION |
| `lpb-devstack tag-repos --branch dev` | Tag on dev branches (`lpb-dev`/`dev`) |
| `lpb-devstack tag-repos --branch main` | Tag on stable branches (`lpb`/`main`) |
| `lpb-devstack tag-repos --version V` | Explicit version (default: devstack VERSION file) |
| `lpb-devstack tag-repos --dry-run` | Show the plan, change nothing |

Tags are created through the local workspace clones (fetch branch →
push tag ref), so normal git auth applies. Already-existing tags are
skipped (re-runs are safe). A missing branch aborts immediately — a
partially-tagged stack is a release bug.

### Workspace Management

| Command | Description |
|---|---|
| `lpb-devstack workspace status` | Show branches + alignment for all repos |
| `lpb-devstack workspace sync` | Clone missing repos, create symlinks, align branches, pull latest (the single write path) |
| `lpb-devstack workspace sync-pins` | Sync settings.json pins to the pipeline's stack version |

### Stack Validation

| Command | Description |
|---|---|
| `lpb-devstack validate` | Full stack alignment check (repos, branches, pins, env) |
| `lpb-devstack validate-hooks` | Run the full devstack pre-commit checks (tests included) |

### Release Promotion

| Command | Description |
|---|---|
| `lpb-devstack release status` | Pre-flight check: all 6 repos, non-destructive |
| `lpb-devstack release promote --dry-run` | Inspect plan without making changes |
| `lpb-devstack release promote` | Promote dev → main (interactive confirmation) |

`promote` does per repo (dev branch → stable branch: `dev` → `main` for
devstack/config/lpb-memory, `lpb-dev` → `lpb` for pi/pi-subagents/
lemonade-pi-plugin):
- **Fast-forward / clean merge**: resets the local stable branch to
  `origin/<stable>`, merges `origin/<dev>`, pushes
- **Unrelated histories** (first release): requires `--rebase` — replaces
  the stable branch with the dev history and force-pushes
  (`git push --force-with-lease`)
- **Conflict**: leaves the repo untouched, reports it
- **Dirty local repo**: skipped, reported
- **Local stable branch ahead of origin** (unpushed commits): skipped with
  guidance — delete the local branch (`git branch -D <stable>`, only with
  explicit confirmation) and re-run
- **devstack only**: strips the `-dev` VERSION suffix (e.g.
  `0.0.58-lpb-dev` → `0.0.58-lpb`) and commits it

Flags: `--yes` (skip confirmation), `--dry-run` (plan only), `--rebase`
(first-release mode).

### Pipeline Override

Every command accepts a pipeline flag:

```bash
lpb-devstack --tag main validate          # validate against stable pipeline
lpb-devstack --tag dev workspace sync     # sync dev pipeline repos
```

## Manual Tagging Flow (dev)

```bash
# 1. Work happens on dev as usual (CI runs tests on every push)
# 2. When ready to ship:
lpb-devstack bump                 # 0.0.57-lpb-dev → 0.0.58-lpb-dev (+ commit)
git push origin dev               # CI sees the VERSION change → build + tag
# 3. Verify:
lpb-devstack workspace status
lpb-devstack validate
```

## Manual Tagging Flow (stable release)

```bash
lpb-devstack release status                    # readiness check
lpb-devstack release promote --dry-run         # inspect plan
lpb-devstack release promote                   # dev → stable + push
lpb-devstack tag-repos --branch main           # tag the 5 repos on stable branches
lpb-devstack --tag main workspace sync-pins   # pins → stable tag
pi update --extensions
```

## Quick Reference

```bash
# Ship a new dev image
lpb-devstack bump --push

# Where do the repos stand?
lpb-devstack workspace status
lpb-devstack validate

# Full pre-commit gate (VERSION format, pins, cleanliness, tests)
lpb-devstack validate-hooks
```
