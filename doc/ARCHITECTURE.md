# Single Image Architecture — Status & Notes

## Current State

The system uses a **single image** pulled with `lpb` or direct podman/docker:

```bash
podman run -it --network host --userns keep-id \
  -v /path/to/project:/home/dev/workspace/<project>:Z \
  ghcr.io/localpibox/devstack:latest
```

- **Bind mount** for workspace (`$PROJECT:/home/dev/workspace/<project>:Z`)
- **`network_mode: host`** for direct host service access (Lemonade)
- **User namespace** (`--userns keep-id` for podman, no-op for docker)
- **First-run init** in `start.sh` (directories, config sync, npm config)
- **Runtime extension install/update** via `start.sh → update.sh --extensions → pi update --extensions`
- **Single-stage Dockerfile** — no extensions baked in (installed at boot)
- **Published** to GitHub Container Registry (`ghcr.io/localpibox/devstack:latest`)

## Known & Resolved Items

| Item | Status | Notes |
|------|--------|-------|
| UID/GID Mismatch | **Resolved** | `--userns keep-id` (podman) / `--user=1000` (docker) |
| Persistent State | **Resolved** | Bind mount `~/.localpibox/state:/home/dev/.pi:Z` |
| Docker Compose removed | **Resolved** | Single image + `lpb` is canonical |
| Extension updates | **Resolved** | `pi update --extensions` at every boot — installs missing, upgrades stale |
| Image size | **Resolved** | Extensions installed at runtime (not baked in) — saves ~250MB |
| First-run slowness | **Partial** | Bootstrap is fast; extensions download on first boot |
| VSCodium port | **Resolved** | `LPB_ED_PORT` env var accepted (defaults: 3000) |
| Config repo sync | **Resolved** | `github.com/localpibox/config` cloned at build time, synced at first run |

## Current Architecture

```
Host:
  ~/projects/myproject/    ← bind mount → /home/dev/workspace/myproject/
  ~/.localpibox/state/     ← bind mount → /home/dev/.pi (agent state, skills, agents)
  ~/.localpibox/agent-browser/ ← bind mount → /home/dev/.agent-browser (browser sessions)
  Lemonade (:13305)        ← host network → 127.0.0.1:13305

Image (localpibox/devstack:latest):
  ── baked in ──────
  Ubuntu 26.04 + Node 24
  Pi monorepo (built from source, with patches)
  VSCodium server (headless, no Chrome)
  agent-browser + exa-mcp-server + zod (global npm)
  Support tools (install-browser, validate, start.sh)

  ── runtime (every boot) ──
  /home/dev/workspace     ← bind mount (project folder)
  /home/dev/.pi           ← bind mount (persistent state)
  pi-powerline-footer     ← installed via pi update --extensions → npm:@latest
  pi-mcp-adapter          ← same
  @tintinweb/pi-subagents  ← same
  lemonade-pi-plugin      ← git clone + checkout from configured ref
  pi-hermes-memory        ← git clone + checkout from configured ref
```

## Extension Update Flow

```
Container boot (start.sh)
  ├─ First run: directories, npm config, config sync
  │
  └─ Every boot: ───────────────────────────────────
     update.sh --extensions
       → pi update --extensions
         For each package in settings.json:
           ├─ npm:* → npm view <pkg> version → compare → npm install <pkg>@latest
           └─ git:* → git fetch + git reset --hard <ref>
         Only updates what differs from latest.
```

## Run (via lpb)

```bash
lpb /path/to/project          # Run with defaults
lpb /path/to/project --port 8080  # Custom editor port
```

### Manual podman command

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
Patch version numbers live in 3 places: Dockerfile ARGs, versions.env,
and the runtime scripts. A central defaults file would reduce maintenance burden.
