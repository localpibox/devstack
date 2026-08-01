# Stack Upkeep — Maintenance System

This directory contains tools for maintaining the LocalPibox stack. It handles:

1. **Patch management** — keeping local changes separate from upstream
2. **Upstream monitoring** — detecting when upstream has new releases
3. **Docker build integration** — applying patches during container builds

## Quick Start

```bash
# Check if upstream has new updates
./stack-upkeep/scripts/check-updates.sh

# Validate stack health
./stack-upkeep/scripts/validate-status.sh
```

## Architecture

```
stack-upkeep/
├── versions.env              # Version tracking + config
├── patches/                  # Patch files (reference + runtime use)
│   ├── pi-qwen-chat-template.patch    # Pi: reasoning_effort for qwen-chat-template
│   └── lemonade-qwen-vision.patch     # Lemonade: Qwen reasoning + vision
├── scripts/
│   ├── check-updates.sh      # Check upstream status
│   ├── validate-status.sh    # Full stack health check
└── README.md                 # This file
```

## Managing Patches

### When upstream updates

1. **Check what changed:**
   ```bash
   ./stack-upkeep/scripts/check-updates.sh
   ```

2. **Update the patch branch:**
   ```bash
   # For Pi:
   cd ~/.pi/agent/git/github.com/localpibox/pi
   git fetch upstream main
   git checkout patches/qwen-reasoning-effort
   git rebase upstream/main
   
   # For Lemonade:
   cd ~/.pi/agent/git/github.com/localpibox/lemonade-pi-plugin
   git fetch upstream main
   git checkout patches/qwen-vision
   git rebase upstream/main
   ```

3. **If a patch conflicts:**
   - Resolve conflicts manually in the working tree
   - `git add <resolved-files>` then `git rebase --continue`
   - Re-extract the patch: `git format-patch upstream/main --stdout > patches/xxx.patch` (for reference)

4. **Rebuild container (if you changed versions.env):**
   ```bash
   cd /home/dev/workspace
   podman build -t ghcr.io/localpibox/devstack:latest .
   ```

### Adding a new patch

```bash
# 1. On the patch branch, make your changes
git checkout patches/qwen-reasoning-effort
# ... make edits ...
git add .
git commit -m "feat: add new patch description"

# 2. Generate the patch file
git format-patch upstream/main --stdout > patches/new-patch.patch

# 3. Push the branch
git push origin patches/qwen-reasoning-effort
```

### Removing a patch (upstream absorbed it)

1. Check if the upstream already has the functionality
2. If yes, remove the patch file from `patches/`
3. Push the branch and rebuild

## Cache Invalidation

The Dockerfile uses `ARG` variables for cache invalidation:

- `PI_BRANCH` / `PI_FORK` — change to invalidate the Pi build layer (clones a different branch)
- `LEMONADE_BRANCH` / `LEMONADE_FORK` — change to invalidate the Lemonade layer

Patches are baked into fork branches — no version counter needed. The fork branch
(e.g. `patches/qwen-reasoning-effort`) already contains all patches as commits.
Changing `pi_branch` in `versions.env` automatically picks up new patches on next build.

The `pi-agent-state` volume (containing your memory, extensions, and config) is preserved across rebuilds.

## Repository Branch Structure

### Pi Monorepo (`localpibox/pi`)

| Branch | Purpose |
|---|---|
| `main` | Legacy — tracks localpibox main (use patches branch instead) |
| `patches/qwen-reasoning-effort` | **Active** — upstream/main + local Qwen patches |

### Lemonade Plugin (`localpibox/lemonade-pi-plugin`)

| Branch | Purpose |
|---|---|
| `main` | Legacy — tracks localpibox main |
| `patches/qwen-vision` | **Active** — upstream/main + Qwen reasoning + vision patches |

### Memory Extension (`localpibox/pi-hermes-memory`)

| Branch | Purpose |
|---|---|
| `fix/subprocess-provider` | **Active** — subprocess provider fixes |
| `main` | Upstream main |
