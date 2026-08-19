# lpb-config Reference

`lpb-config` is the single tool for managing the **config repo**, **workspace
sync**, **validation**, and **stable releases**. It runs inside the devstack
container at boot and provides the subcommands documented below.

## Commands

### Validation & Workspace

| Command | Description |
|---|---|
| `lpb-config validate` | Validate entire stack alignment (repos, branches, pins) |
| `lpb-config workspace status` | Show branches + alignment for all repos |
| `lpb-config workspace sync` | Sync git repos (clone/fetch/merge) to current branches |
| `lpb-config workspace sync --extensions` | Sync settings.json pins to stack version |
| `lpb-config workspace ensure [--fix]` | Check/fix branch alignment for pipelines |

### Pipeline Override

Every command above accepts a pipeline flag:

```bash
lpb-config --tag main validate      # validate against stable pipeline
lpb-config --tag dev workspace sync # sync dev pipeline repos
```

### Memory Management

| Command | Description |
|---|---|
| `lpb-config memory show` | Display current lpb-memory configuration |
| `lpb-config memory setup` | Interactive wizard to configure lpb-memory |

### Config Repo Management

| Command | Description |
|---|---|
| `lpb-config status` | Show config repo state |
| `lpb-config update` | Pull latest config repo changes |
| `lpb-config reset` | Reset config repo to clean state |

### Release (promote dev → main)

| Command | Description |
|---|---|
| `lpb-config release status` | Pre-flight check: all 6 repos, non-destructive |
| `lpb-config release promote --dry-run` | Inspect plan without making changes |
| `lpb-config release promote` | Promote dev → main (interactive confirmation) |

`promote` does per-repo:
- **Fast-forward / clean merge**: resets local stable branch to `origin/main`,
  merges `origin/dev`, pushes
- **Unrelated histories** (first release): requires `--rebase` — replaces
  stable branch with dev history and force-pushes
- **Conflict**: leaves repo untouched, reports it
- **Dirty local repo**: skipped, reported with guidance
- **devstack only**: strips `-dev` VERSION suffix (e.g. `0.0.46-lpb-dev` → `0.0.46-lpb`)

Flags: `--yes` (skip confirmation), `--dry-run` (plan only), `--rebase`
(first-release mode).

### Align

| Command | Description |
|---|---|
| `lpb-config align` | Update extension pins in settings.json to latest GitHub tags |

## Settings.json Lifecycle

Settings.json is **template-driven**, not git-tracked:

1. Config repo ships `settings.json.template` with `__LPB_VERSION__` placeholders
2. First boot: `start.sh` generates `settings.json` (replaces placeholders)
3. No model/provider preconfigured — user runs `/login lemonade`
4. Pin sync: `lpb-config workspace sync --extensions` (main pipeline reads
   stable version from devstack `origin/main`)
5. `lpb-config validate` checks pins match the current stack version
6. Settings.json persists on the host volume — survives container rebuilds

Example pin: `git:github.com/lpb-stack/pi-subagents@0.0.46-lpb-dev`

## lpb-memory Config Lifecycle

Same template-driven pattern:

1. First boot: `start.sh` copies `lpb-memory-config.json.template` → config
2. No model override — uses the main model until user configures
3. Tune: `lpb-config memory setup` (interactive wizard)
4. Review: `lpb-config memory show`

## Quick Reference

```bash
# Check stack health
lpb-config validate

# See where repos stand
lpb-config workspace status

# Fix branch alignment
lpb-config workspace ensure --fix

# Update extension pins
lpb-config workspace sync --extensions

# Check memory config
lpb-config memory show

# Configure memory
lpb-config memory setup

# Check if ready to promote
lpb-config release status

# Preview the promote plan
lpb-config release promote --dry-run

# Actually promote
lpb-config release promote
```
