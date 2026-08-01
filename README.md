# LocalPibox Devstack

AI-powered development environment with the Pi coding agent, VSCodium editor, and agent-browser automation — all containerized.

## Quick Start

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
podman exec -it localpobox update --extensions

# Update only patches
podman exec -it localpibox stack.sh update --patches
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
                    │  (fast)      │
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

## Current Patches Baked Into the Image

Patches are **baked into fork branches** at Docker build time. The
Dockerfile clones Pi from a pre-patched fork branch, so no `git am` runs at
build or runtime, and `update --patches` is reference-only inside the running
container (the source tree is not shipped). The `.patch` files in
`stack-upkeep/patches/` are **reference documentation** of what each fork
branch contains; the authoritative branch list lives in
`stack-upkeep/versions.env`. Run `./stack.sh status` for a live validation.

### Pi monorepo — `localpibox/pi` @ `patches/qwen-reasoning-effort`

Installed version: **0.83.0** (`pi --version`).

| Patch (reference file) | What it does | File affected |
|---|---|---|
| `pi-qwen-chat-template.patch` | Send `reasoning_effort` (high/medium/low) for Qwen models via the `qwen` and `qwen-chat-template` thinking formats | `packages/ai/api/openai-completions.ts` |
| `pi-overflow-case4.patch` | Add Case 4 to `isContextOverflow`: detect Qwen/Llama.cpp reasoning overflow where models burn the output budget on thinking blocks (`stopReason=length` + `output>0` + input >= 90% of context window) | `packages/ai/src/utils/overflow.ts` |

### Lemonade plugin — `localpibox/lemonade-pi-plugin` @ `patches/api-key-auth`

| Patch (reference file) | What it does | File affected |
|---|---|---|
| `lemonade-api-key-auth.patch` | Register the Lemonade provider with API-key auth type (not oauth), so Pi actually loads the provider | `extensions/index.ts` |
| `lemonade-thinking-format.patch` | Switch Qwen models on the Lemonade (llama.cpp) backend to the `qwen-chat-template` thinking format; Lemonade ignores top-level `enable_thinking`/`reasoning_effort` and only honours `chat_template_kwargs` | `extensions/index.ts` |
| `lemonade-qwen-vision.patch` | Detect vision capability from model labels and expose `image` input support | `extensions/index.ts` |
| `lemonade-qwen-thinking-format.patch` (multi-patch series) | Companion reasoning/vision-detection changes for Qwen on Lemonade | `extensions/index.ts` |

### Memory extension — `localpibox/pi-hermes-memory` @ `fix/subprocess-provider`

Reactive model-override propagation across all LLM subprocess paths.

### Upstreaming policy

These patches are **candidate upstream contributions**. They are sent upstream
(to `earendil-works/pi`, `lemonade-sdk/lemonade-pi-plugin`, and
`localpibox/pi-hermes-memory`) **after testing**, and **only if generally
useful and not too opinionated** for this stack's specific configuration.
Patches that are local-workaround-specific or that diverge from upstream design
direction stay on the LocalPibox fork branch.

## CI/CD

Built automatically on GitHub Actions when:
- Push to `main` (Dockerfile, support/, stack-upkeep/)
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
├── Dockerfile                 # Single-stage build (all in one image)
├── run.sh                     # Local launcher script (optional)
├── stack.sh                   # Stack management (copied into image)
├── .github/workflows/         # CI/CD pipeline
├── stack-upkeep/              # Patch management system
│   ├── versions.env           # Version tracking
│   ├── patches/               # Git patch files
│   └── scripts/               # Maintenance scripts
├── support/                   # Entrypoint scripts
│   ├── start.sh               # Container entrypoint
│   ├── install-browser.sh     # Browser setup script
│   └── validate.sh            # Health validation
├── .env.example               # Template — copy to .env for real values
└── .env                       # Local env vars (gitignored)
```

## Related Repositories

- [localpibox/pi](https://github.com/localpibox/pi) — Forked Pi monorepo with Qwen reasoning support
- [localpibox/lemonade-pi-plugin](https://github.com/localpibox/lemonade-pi-plugin) — Lemonade provider plugin
- [localpibox/config](https://github.com/localpibox/config) — Pi configuration (settings, mcp, skills)
- [localpibox/pi-hermes-memory](https://github.com/localpibox/pi-hermes-memory) — Memory extension
