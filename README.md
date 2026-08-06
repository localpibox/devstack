# LocalPibox Devstack

AI-powered development environment with the Pi coding agent, VSCodium editor, and agent-browser automation — all containerized.

## Quick Start

### Option 1: One-line installer (recommended)

```bash
# Install the `lpb` launcher (adds it to ~/.local/bin/)
curl -fsSL https://raw.githubusercontent.com/localpibox/devstack/main/scripts/install.sh | bash

# Run devstack for your project
lpb /path/to/your/project

# Or start VSCodium with a welcome screen (user picks project)
lpb

# Common commands
lpb --stop      # Stop the container
lpb --logs      # View logs
lpb --remove    # Remove everything
lpb --config    # Show config file
lpb --help      # Full usage
```

### Option 2: Manual podman run

```bash
# Pull the latest image
podman pull ghcr.io/localpibox/devstack:latest

# Run with a project folder
podman run -d --name localpibox --network host --userns keep-id \
    -v /path/to/your/project:/home/dev/workspace/myproject:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    -e ED_PORT=3000 \
    ghcr.io/localpibox/devstack:latest

# Open browser to http://localhost:3000 (token: devsession)
```

### Interactive mode

```bash
# Run and get a shell inside the container
podman run -it --name localpibox --network host --userns keep-id \
    -v /path/to/your/project:/home/dev/workspace/myproject:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    -e ED_PORT=3000 \
    ghcr.io/localpibox/devstack:latest
```

### Update extensions (no rebuild)

```bash
# Inside the running container
podman exec -it localpibox update --extensions
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Host                                               │
│                                                     │
│  ~/projects/myproject/  ──mount──→  /workspace/myproject/  │
│  ~/.localpibox/state/     ──mount──→  /home/dev/.pi/       │
│  ~/.localpibox/agent-browser/ ──→ /home/dev/.agent-browser/ │
│  Lemonade (:13305)      ──network→  http://127.0.0.1     │
└─────────────────────────────────────────────────────┘

Image: ghcr.io/localpibox/devstack:latest
  ├─ Ubuntu 26.04 + Node.js 24
  ├─ Pi monorepo (built, patched)
  ├─ VSCodium server (headless, port 3000)
  ├─ Chrome (agent-browser automation)
  ├─ Extensions: lemonade, memory, mcp-adapter, subagents
  └─ Config: settings, mcp, skills, agents
```

## Commands Available Inside Container

Once the container is running, these commands are available:

| Command | Description |
|---|---|
| `pi` | Start Pi CLI |
| `update --extensions` | Update extensions to latest |
| `update --patches` | Apply Pi source patches |
| `exit` | Stop the server and exit |

### Update examples

```bash
# Update extensions to latest release
podman exec -it localpibox update --extensions

# Patches are baked into the image — to update, rebuild the container
# with updated fork branches in lpb.stack.env.
```

## Usage

### Single project

```bash
# Run with any project folder
podman run -d --name localpibox --network host --userns keep-id \
    -v /home/user/projects/myproject:/home/dev/workspace/myproject:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    ghcr.io/localpibox/devstack:latest
```

The project mounts at `/workspace/myproject/` so tools see the correct project name (not "workspace").

### Multiple projects

```bash
# First project
podman run -d --name localpibox --network host --userns keep-id \
    -e ED_PORT=3000 \
    -v /path/to/project-a:/home/dev/workspace/project-a:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    ghcr.io/localpibox/devstack:latest
# → http://localhost:3000

# Stop and run another
podman stop localpibox
podman rm localpibox

podman run -d --name localpibox --network host --userns keep-id \
    -e ED_PORT=3001 \
    -v /path/to/project-b:/home/dev/workspace/project-b:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    ghcr.io/localpibox/devstack:latest
# → http://localhost:3001
```

## Update Flow

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│  GitHub      │  ──→ │  CI/CD        │  ──→ │  GHCR            │
│  (your code) │      │  (fast net)   │      │  (image)         │
└──────────────┘      └───────────────┘      └──────────────────┘
                                                        │
                    ┌──────────────┐                    │
                    │  Podman Pull │◄───────────────────┘
                    │  (no timeout,│
                    │  streaming) │
                    └──────────────┘
                          │
                    ┌──────────────┐
                    │  Podman Run  │
                    │  (launch)    │
                    └──────────────┘
                          │
                    ┌──────────────┐
                    │  update      │◄── Extensions updated at boot
                    │  --extensions│     via pi update --extensions
                    └──────────────┘
```

### What gets updated:

| Component | How | Frequency |
|---|---|---|
| Base image | CI/CD on push to main | Every code change |
| Extensions | `pi update --extensions` (at boot) | Every container start |
| Chrome/VSCodium | Base image rebuild | Monthly or on-demand |
| lpb launcher | `lpb --update` self-update | Every code change |

**Note:** Pulls may take a while on slow connections — `lpb --update` uses
non-blocking streaming so you'll see real-time progress (no timeouts).

## Version Configuration

Fork branches and versions are tracked in `lpb.stack.env` at the repo root.
Change these to rebuild with different versions. Extensions inside the container
are updated with: `podman exec -it localpibox pi update --extensions`

### Pi monorepo — `localpibox/pi` @ `patches/qwen-reasoning-effort`

Installed version: **0.83.0** (`pi --version`). Fork branch contains cumulative
patches including: reasoning effort for Qwen models, Case 4 context overflow
detection, Qwen chat-template thinking format support.

### Pi monorepo — `localpibox/pi` @ `patches/qwen-reasoning-effort`

Installed version: **0.83.0** (`pi --version`).

| Patch (reference file) | What it does | File affected |
|---|---|---|
| `pi-qwen-chat-template.patch` | Send `reasoning_effort` (high/medium/low) for Qwen models via the `qwen` and `qwen-chat-template` thinking formats | `packages/ai/api/openai-completions.ts` |
| `pi-overflow-case4.patch` | Add Case 4 to `isContextOverflow`: detect Qwen/Llama.cpp reasoning overflow where models burn the output budget on thinking blocks (`stopReason=length` + `output>0` + input >= 90% of context window) | `packages/ai/src/utils/overflow.ts` |

### Lemonade plugin — `localpibox/lemonade-pi-plugin` @ `patches/api-key-auth`

Fork branch includes: API-key auth type registration, Qwen thinking format
support, vision capability detection, and reasoning format handling.

### Memory extension — `localpibox/pi-hermes-memory` @ `fix/subprocess-provider`

Reactive model-override propagation across all LLM subprocess paths.

### Upstreaming policy

These patches are **candidate upstream contributions**. They are sent upstream
(to `earendil-works/pi`, `lemonade-sdk/lemonade-pi-plugin`, and
`localpibox/pi-hermes-memory`) **after testing**, and **only if generally
useful and not too opinionated** for this stack's specific configuration.
Patches that are local-workaround-specific or that diverge from upstream design
direction stay on the LocalPibox fork branch.

## Forking & Repointing

You can fork this repo, personalize it, and repoint it at your own managed
set of repositories (Pi core, config preset, and extensions) instead of the
LocalPibox originals.

### What each component maps to

| Component | URL / ref lives in | Effort | Repoint path |
|---|---|---|---|
| **Extensions** (lemonade-pi-plugin, lpb-memory, pi-subagents, …) | runtime config `~/.pi/agent/settings.json` → `packages` | 🟢 trivial, **no rebuild** | edit the `packages` array, or `pi install git:<fork>/<repo>`; applied at next startup via `pi update --extensions` |
| **Config preset** (localpibox/config) | `lpb.stack.env` → `LPB_CONFIG_FORK` / `LPB_CONFIG_REF` | 🟡 one rebuild, or no rebuild at runtime | rebuild `--build-arg CONFIG_FORK=...`, **or** `git -C ~/.local/pi-config remote set-url origin <fork>` (no rebuild) |
| **Pi core** (localpibox/pi) | `lpb.stack.env` → `LPB_PI_FORK` / `LPB_PI_REF` | 🔴 image rebuild | fork `localpibox/pi`, set engine + `LPB_IMAGE_CLI`, rebuild |
| **Dev workspace checkout** (all repos into `workspace/`) | `tools/workspace.manifest.json` | 🟢 easy | edit manifest URLs/refs (used by `sync-workspace.py`) |

### Full repoint procedure (image build)

1. Fork the repos you care about (e.g. `localpibox/pi`, `localpibox/config`).
2. Clone **this** repo (devstack) and edit `lpb.stack.env` at the root to point
   at your forks:

   ```sh
   export LPB_PI_FORK=https://github.com/<you>/pi.git
   export LPB_PI_REF=main                 # your branch
   export LPB_CONFIG_FORK=https://github.com/<you>/config.git
   export LPB_CONFIG_REF=main             # your branch
   export LPB_IMAGE_CLI=ghcr.io/<you>/devstack:cli
   export LPB_IMAGE_WEB=ghcr.io/<you>/devstack:web
   export LPB_CONTAINER_NAME=mybox        # avoid colliding with localpibox
   ```

   (Or pass them as `docker build --build-arg PI_FORK=... --build-arg
   CONFIG_FORK=...` without editing the file.)
3. Build and push the image (locally, or via the GitHub Actions workflow,
   which reads `lpb.stack.env`).
4. Install/run `lpb` — it reads the same `lpb.stack.env` for image/container
   names, so it picks up your fork automatically.
5. Point the launcher at your image
   `~/.localpibox/devstack/config` → `export
   LPB_IMAGE_NAME="ghcr.io/<you>/devstack:latest"`, or let the forked
   `lpb` handle it.

### Repointing the config preset without a rebuild

The config preset is a git clone at `~/.local/pi-config` (container). After
first boot you can repoint it live — no image rebuild needed:

```sh
podman exec -it localpibox bash
cd ~/.local/pi-config
git remote set-url origin https://github.com/<you>/config.git
git pull --ff-only origin <your-branch>
# re-seed the runtime copy from your preset
cp settings.json mcp.json pi-defaults.json subagents.json ~/.pi/agent/ 2>/dev/null || true
```

### Repointing extensions at runtime (no rebuild)

Extensions are not baked in; they are installed on first boot from
`settings.json#packages`. Repoint them from the running container:

```sh
podman exec -it localpibox pi remove git:github.com/localpibox/lemonade-pi-plugin
podman exec -it localpibox pi install git:github.com/<you>/lemonade-pi-plugin@<your-branch>
podman exec -it localpibox pi update --extensions
```

Changes apply at the **next pi startup** (or `/reload` in a running session
for config).

> **Note:** `lpb.stack.env` controls the image build and `pi` fork;
> `tools/workspace.manifest.json` independently controls the dev-workspace
> checkout used by `sync-workspace.py`. They are separate by design.

## CI/CD

Built automatically on GitHub Actions when:
- Push to `main` (Dockerfile, support/, lpb.stack.env)
- Weekly (Monday 3am UTC) — keeps image fresh
- Manual dispatch with flags

### Actions used (all latest versions, Node.js 24 native)

- `actions/checkout@v6`
- `docker/build-push-action@v7`
- `docker/setup-buildx-action@v4`
- `docker/setup-qemu-action@v4`
- `docker/login-action@v4`
- `docker/metadata-action@v6`
- `actions/upload-artifact@v7`

## Troubleshooting

### Port already in use

```bash
# Check who's using the port
lsof -i :3000

# Stop existing container
podman stop localpibox
podman rm localpibox

# Run with new port
podman run -d --name localpibox --network host --userns keep-id \
    -e ED_PORT=8080 \
    -v /path/to/project:/home/dev/workspace/myproject:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    ghcr.io/localpibox/devstack:latest
# → http://localhost:8080
```

### Auth token expired

```bash
# Login in the editor (Ctrl+Shift+P → "Pi: Login")
# Or via CLI
podman exec -it localpibox pi login
```

### Outdated extensions

```bash
podman exec -it localpibox update --extensions
```

### Need a rebuild

```bash
# Pull from GHCR (newer build)
podman pull ghcr.io/localpibox/devstack:latest
podman stop localpibox && podman rm localpibox
podman run -d --name localpibox --network host --userns keep-id \
    -v /path/to/project:/home/dev/workspace/myproject:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    -v ~/.localpibox/agent-browser:/home/dev/.agent-browser:Z \
    ghcr.io/localpibox/devstack:latest
```

## Directory Structure

```
devstack/
├── Dockerfile                 # Multi-stage build (cli + web targets)
├── lpb.stack.env          # Fork/version tracking (forks, branches, base versions)
├── doc/                   # Architecture and operational docs
├── scripts/                   # Launcher and installer
│   ├── lpb                    # lpb launcher (bash wrapper → lpb.py)
│   ├── lpb.py                 # lpb launcher (Python implementation)
│   └── install.sh             # One-line installer script
├── support/                   # Entrypoint scripts
│   ├── entrypoint-cli.sh      # CLI image entrypoint (Pi CLI foreground)
│   ├── entrypoint-web.sh      # Web image entrypoint (VSCodium server)
│   ├── install-browser.sh     # Browser setup script
│   ├── start.sh               # Legacy entrypoint (superseded by entrypoint-*)
│   └── validate.sh            # Health validation
├── .env.example               # Template — copy to .env for real values
└── .env                       # Local env vars (gitignored)
```

## Related Repositories

- [localpibox/pi](https://github.com/localpibox/pi) — Forked Pi monorepo with Qwen reasoning support
- [localpibox/lemonade-pi-plugin](https://github.com/localpibox/lemonade-pi-plugin) — Lemonade provider plugin
- [localpibox/config](https://github.com/localpibox/config) — Pi configuration (settings, mcp, skills)
- [localpibox/pi-hermes-memory](https://github.com/localpibox/pi-hermes-memory) — Memory extension
