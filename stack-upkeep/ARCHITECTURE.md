# Single Image Architecture — Status & Notes

## Current State (Resolved)

The system uses a **single image** pulled with `run.sh` or direct podman/docker:

```bash
run.sh /path/to/project
podman run -it --network host --userns keep-id \
  -v /path/to/project:/home/dev/workspace/<project>:Z \
  ghcr.io/localpibox/devstack:latest
```

- **Bind mount** for workspace (`$PROJECT:/home/dev/workspace/<project>:Z`)
- **`network_mode: host`** for direct host service access (Lemonade)
- **User namespace** (`--userns keep-id` for podman, no-op for docker)
- **First-run init** in `start.sh` (extensions, directories, auto-detect)
- **Runtime extension updates** via `stack.sh update` or `./host-load-updates.sh`
- **Multi-stage Dockerfile** with build-time extension install
- **Published** to GitHub Container Registry (`ghcr.io/localpibox/devstack:latest`)

## Known & Resolved Items

| Item | Status | Notes |
|------|--------|-------|
| UID/GID Mismatch | **Resolved** | `--userns keep-id` (podman) / `--user=1000` (docker) |
| Persistent State | **Resolved** | Bind mount `$HOME/.localpibox/state:/home/dev/.pi:Z` |
| Docker Compose removed | **Resolved** | Single image + `run.sh` is the canonical path |
| Extension updates | **Resolved** | `stack.sh update` / `./host-load-updates.sh` handles runtime updates |
| Image size | **Partial** | Multi-stage build implemented; Chrome deferred to runtime |
| First-run slowness | **Partial** | `start.sh` has fast bootstrap; extensions installed at build time |
| VSCodium port | **Resolved** | `LPB_ED_PORT` env var accepted (defaults: 3000) |
| Config repo sync | **Resolved** | `github.com/localpibox/config` cloned at build time, synced at first run |

## Current Architecture

```
Host:
  ~/.localpibox/
    state/           ← bind-mounted to /home/dev/.pi (agent state, skills, agents)
    agent-browser/   ← bind-mounted to /home/dev/.agent-browser (browser sessions)

Image (localpibox/devstack:latest):
  ── baked in ──────
  Ubuntu 26.04 + Node 24
  Pi monorepo (built, with patches)
  Lemonade plugin + memory extension
  VSCodium server (headless, no Chrome)
  agent-browser + exa-mcp + global npm packages
  All config (settings.json, mcp.json, skills, agents)
  Support tools (install-browser, validate, load-updates)

  ── runtime ───────
  /home/dev/workspace   ← bind mount (project folder)
  /home/dev/.pi         ← bind mount (state)
  CHROME_PATH           ← set automatically by install-browser
  LPB_ED_PORT           ← env var for editor port
  LPB_DEVCONTAINER_WORKSPACE_DIR ← workspace path
```

## Run (via run.sh)

```bash
./run.sh /path/to/project          # Run with defaults
./run.sh /path/to/project --port 8080  # Custom editor port
./run.sh /path/to/project --pull    # Pull latest image first
```

Mount structure:
- Host: `$PROJECT → /home/dev/workspace/<project>/`
- Host: `~/.localpibox/state → /home/dev/.pi` (persistent agent state)
- Host: `~/.localpibox/agent-browser → /home/dev/.agent-browser` (browser sessions)

## Remaining Risks

### 1. Browser availability ⚠️ (Low risk)
Chrome is installed on-demand via `install-browser`. If a user tries browser
automation without running it first, they'll get a cryptic Playwright error.

### 2. No ARM support (planned)
Current CI builds only `linux/amd64`. QEMU setup exists but ARM not targeted.

### 3. Version defaults duplicated (planned)
Patch version numbers live in 4 places: Dockerfile ARGs, versions.env, stack.sh
fallbacks, .env-patches. A central defaults file would reduce maintenance burden.
