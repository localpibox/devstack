# Single Image Architecture — Analysis & Plan

## Current State

The system uses Docker Compose with:
- **Named volumes** for `.pi` (agent state), `.npm` (cache), browser states
- **Bind mount** for workspace (`$WORKSPACE_DIR:/home/dev/workspace`)
- **`network_mode: host`** for direct host service access (Lemonade)
- **User namespace** (`userns_mode: keep-id`) for rootless Podman
- **First-run init** in `start.sh` (extensions, auth config, directories)

## Proposed: Single Reusable Image

A single image that users pull and run with a project folder mount:

```bash
podman run --rm -it \
  --network host \
  -v $HOME/projects/myproject:/home/dev/workspace:Z \
  -v $HOME/.localpibox/pi-state:/home/dev/.pi \
  ghcr.io/localpibox/devstack:latest
```

## Key Issues & Risks

### 1. UID/GID Mismatch ⚠️ (Medium Risk)
**Problem**: Image creates `dev` user with UID 1000. If host user has a different UID, bind-mounted files are owned by the wrong user.
**Impact**: Permission errors on workspace files after container stops.
**Fix**: Accept UID as runtime arg, or set workspace ownership on first run.

### 2. Persistent State Location ⚠️ (Medium Risk)
**Problem**: Current named volumes (`pi-agent-state`, etc.) don't work with bare `podman run` without compose.
**Impact**: Need to decide between:
- Named volumes (managed by podman, opaque)
- Bind mounts (user-controlled, easy to backup/clone)
**Recommendation**: Use bind mounts for state directories — user controls backup.

### 3. Extension Updates 🔴 (High Risk)
**Problem**: Extensions are installed at **build time**. Updating an extension requires rebuilding the image.
**Impact**: Extensions become stale quickly; every extension update means a new image build.
**Fix**: Install extensions at **runtime** from a config file, or add an `/update-extensions` command.

### 4. Image Size 🔴 (High Risk)
**Problem**: Current image is large (~2GB+) due to VSCodium, Chrome, Node, Pi, build deps.
**Impact**: Pull takes time; storage adds up with multiple tags.
**Fix**: Use multi-stage build to strip build deps from final image.

### 5. First-Run Slowness 🔴 (High Risk)
**Problem**: `start.sh` has idempotent install with retries (4 attempts, 10s delays). On a fresh volume this takes ~60s.
**Impact**: Every new user feels a long startup.
**Fix**: Pre-install common extensions in image, only do runtime config.

### 6. Host Service Discovery ⚠️ (Low Risk)
**Problem**: `network_mode: host` requires Lemonade on host. No discovery fallback.
**Impact**: Fails silently if Lemonade isn't running.
**Fix**: Already handled by `start.sh` (waits 60s with health check).

### 7. VSCodium Port Conflict ⚠️ (Low Risk)
**Problem**: Editor always uses port 3000. Can't run two instances on same host.
**Impact**: Limits parallel usage.
**Fix**: Accept `ED_PORT` env var (already exists in compose).

### 8. Auth Persistence ⚠️ (Low Risk)
**Problem**: `auth.json` is written at every container start. Stale tokens may not refresh.
**Impact**: Auth failures after token expiry.
**Fix**: Add token refresh logic, or accept that users need to `/login` periodically.

## Recommended Architecture

```
Host:
  ~/.localpibox/
    pi-state/          ← bind-mounted to /home/dev/.pi (persistent agent state)
    extensions/        ← bind-mounted optional extensions (runtime install)
    config.json        ← per-user overrides (merged with image defaults)

Image (localpibox/devstack:latest):
  ── baked in ──────
  Ubuntu 26.04 + Node 24
  Pi monorepo (built, with patches)
  Lemonade plugin + memory extension
  VSCodium server (headless)
  Chrome (for agent-browser)
  agent-browser + exa-mcp + extensions
  All config (settings, mcp, skills, agents)
  Support tools
  
  ── runtime ───────
  /home/dev/workspace    ← bind mount (project folder)
  /home/dev/.pi          ← bind mount or named volume (state)
  LEMONADE_BASE_URL      ← env var or auto-discovery
  ED_PORT                ← env var for editor port

Run:
  podman run -it --network host \
    -v $HOME/projects/myproject:/home/dev/workspace:Z \
    -v $HOME/.localpibox/pi-state:/home/dev/.pi \
    -e ED_PORT=3000 \
    ghcr.io/localpibox/devstack:latest
```

## Migration Path

1. **Keep Docker Compose** for now — it works and the compose file can become the
   "recommended run recipe" while the image matures.

2. **Create a `run.sh` wrapper** that generates the `podman run` command:
   ```bash
   ./run.sh /path/to/project          # Run with defaults
   ./run.sh /path/to/project --port 8080  # Custom editor port
   ./run.sh /path/to/project --pull    # Pull latest image first
   ```

3. **Move extension install to runtime** (or add `/stack.sh update` command).

4. **Add multi-stage Dockerfile** to reduce final image size.

5. **Publish image** to GitHub Container Registry (`ghcr.io`).

## Immediate Actions

1. Create `run.sh` script for single-image usage
2. Add `/stack.sh update` for runtime extension updates
3. Convert compose file to `run.sh` example
4. Start planning multi-stage Dockerfile (deferred — image size is nice-to-have)
