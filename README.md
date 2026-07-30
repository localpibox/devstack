# LocalPibox Devstack

AI-powered development environment with the Pi coding agent, VSCodium editor, and agent-browser automation — all containerized.

## Quick Start

```bash
# Pull the latest image
podman pull ghcr.io/localpibox/devstack:latest

# Navigate to your project
cd ~/projects/myproject

# Launch devstack
./run.sh /path/to/project
```

Open your browser to `http://localhost:3000` (token: `devsession`).

## Commands

| Command | Description |
|---|---|
| `./run.sh /path/to/project` | Launch devstack for a project |
| `./run.sh /path/to/project --port 8080` | Custom editor port |
| `./run.sh /path/to/project --pull` | Pull latest image first |
| `./stack.sh update --pull` | Load latest updates (no rebuild) |
| `./stack.sh update --extensions` | Update extensions only |
| `./stack.sh update --patches` | Update patches only |

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

## Usage

### Single project

```bash
# Run with any project folder
./run.sh /home/user/projects/myproject
```

The project mounts at `/workspace/myproject/` so tools see the correct project name (not "workspace").

### Multiple projects

```bash
# First project
./run.sh /home/user/projects/project-a --port 3000
# → http://localhost:3000

# Stop and run another
podman stop localpibox
./run.sh /home/user/projects/project-b --port 3001
# → http://localhost:3001
```

### Update without rebuild

```bash
# Pull latest update tarballs from GHCR
./stack.sh update --pull

# Or update specific components
./stack.sh update --extensions    # Update only extensions
./stack.sh update --patches       # Update only patches
```

### Container commands

```bash
# View logs
podman logs -f localpibox

# Stop container
podman stop localpibox

# Remove container
podman rm localpibox

# Manual podman command
podman run -d --name localpibox --network host --userns keep-id \
    -e ED_PORT=3000 \
    -v "$PWD:/home/dev/workspace/myproject:Z" \
    -v "$HOME/.localpibox/state:/home/dev/.pi:Z" \
    ghcr.io/localpibox/devstack:latest
```

## Update Pipeline

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│  GitHub      │  ──→ │  CI/CD        │  ──→ │  GHCR            │
│  (your code) │      │  (fast net)   │      │  (pulled locally)│
└──────────────┘      └───────────────┘      └──────────────────┘
                                                        │
                    ┌──────────────┐                    │
                    │  Local Pull  │◄───────────────────┘
                    │  (fast)      │
                    └──────────────┘
                          │
                    ┌──────────────┐
                    │  ./run.sh    │
                    │  (launch)    │
                    └──────────────┘
                          │
                    ┌──────────────┐
                    │  ./stack.sh  │
                    │  update      │◄── Patch-level updates
                    └──────────────┘
```

### What gets updated:

| Component | How | Frequency |
|---|---|---|
| Base image | CI/CD on push to main | Every code change |
| Pi patches | `./stack.sh update --patches` | When patches change |
| Extensions | `./stack.sh update --extensions` | As needed |
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
./run.sh /path/to/project --port 8080
```

### Auth token expired

```bash
# Login in the editor (Ctrl+Shift+P → "Pi: Login")
# Or via CLI
podman exec -it localpibox pi login
```

### Outdated extensions

```bash
./stack.sh update --pull
```

### Need a rebuild

```bash
# On your local machine
./stack.sh rebuild

# Or pull from GHCR (newer build)
podman pull ghcr.io/localpibox/devstack:latest
./run.sh /path/to/project
```

## Directory Structure

```
devstack/
├── Dockerfile                 # Multi-stage build (builder → runtime)
├── docker-compose.yml         # Compose config (for local builds)
├── run.sh                     # Single-image launcher
├── stack.sh                   # Stack management commands
├── .github/workflows/         # CI/CD pipeline
├── stack-upkeep/              # Patch management system
│   ├── versions.env           # Version tracking
│   ├── patches/               # Git patch files
│   └── scripts/               # Maintenance scripts
└── support/                   # Entrypoint and config files
    └── start.sh               # Container entrypoint
```

## Related Repositories

- [localpibox/pi](https://github.com/localpibox/pi) — Forked Pi monorepo with Qwen reasoning support
- [localpibox/lemonade-pi-plugin](https://github.com/localpibox/lemonade-pi-plugin) — Lemonade provider plugin
- [localpibox/config](https://github.com/localpibox/config) — Pi configuration (settings, mcp, skills)
- [localpibox/pi-hermes-memory](https://github.com/localpibox/pi-hermes-memory) — Memory extension
