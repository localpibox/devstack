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
    -e ED_PORT=3000 \
    ghcr.io/localpibox/devstack:latest
```

### Update extensions/patches (no rebuild)

```bash
# Inside the running container
podman exec -it localpibox stack.sh update --pull
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Host                                               │
│                                                     │
│  ~/projects/myproject/  ──mount──→  /workspace/myproject/  │
│  ~/.localpibox/state/   ──mount──→  /home/dev/.pi/       │
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
| `stack.sh update --pull` | Load latest updates from GHCR |
| `stack.sh update --extensions` | Update only extensions |
| `stack.sh update --patches` | Update only patches |
| `exit` | Stop the server and exit |

### Update examples

```bash
# Pull latest tarballs from GHCR and load
podman exec -it localpibox stack.sh update --pull

# Update only extensions
podman exec -it localpibox stack.sh update --extensions

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
    ghcr.io/localpibox/devstack:latest
# → http://localhost:3000

# Stop and run another
podman stop localpibox
podman rm localpibox

podman run -d --name localpibox --network host --userns keep-id \
    -e ED_PORT=3001 \
    -v /path/to/project-b:/home/dev/workspace/project-b:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    ghcr.io/localpibox/devstack:latest
# → http://localhost:3001
```

## Update Pipeline

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│  GitHub      │  ──→ │  CI/CD        │  ──→ │  GHCR            │
│  (your code) │      │  (fast net)   │      │  (pulled locally)│
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
                    │  Stack.sh    │
                    │  update      │◄── Patch-level updates
                    └──────────────┘
```

### What gets updated:

| Component | How | Frequency |
|---|---|---|
| Base image | CI/CD on push to main | Every code change |
| Pi patches | `stack.sh update --patches` | When patches change |
| Extensions | `stack.sh update --extensions` | As needed |
| Chrome/VSCodium | Base image rebuild | Monthly or on-demand |

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
podman exec -it localpibox stack.sh update --pull
```

### Need a rebuild

```bash
# Pull from GHCR (newer build)
podman pull ghcr.io/localpibox/devstack:latest
podman stop localpibox && podman rm localpibox
podman run -d --name localpibox --network host --userns keep-id \
    -v /path/to/project:/home/dev/workspace/myproject:Z \
    -v ~/.localpibox/state:/home/dev/.pi:Z \
    ghcr.io/localpibox/devstack:latest
```

## Directory Structure

```
devstack/
├── Dockerfile                 # Multi-stage build (builder → runtime)
├── docker-compose.yml         # Compose config (for local builds)
├── run.sh                     # Local launcher script (optional)
├── stack.sh                   # Stack management (copied into image)
├── .github/workflows/         # CI/CD pipeline
├── stack-upkeep/              # Patch management system
│   ├── versions.env           # Version tracking
│   ├── patches/               # Git patch files
│   └── scripts/               # Maintenance scripts
└── support/                   # Entrypoint script
    └── start.sh               # Container entrypoint
```

## Related Repositories

- [localpibox/pi](https://github.com/localpibox/pi) — Forked Pi monorepo with Qwen reasoning support
- [localpibox/lemonade-pi-plugin](https://github.com/localpibox/lemonade-pi-plugin) — Lemonade provider plugin
- [localpibox/config](https://github.com/localpibox/config) — Pi configuration (settings, mcp, skills)
- [localpibox/pi-hermes-memory](https://github.com/localpibox/pi-hermes-memory) — Memory extension
