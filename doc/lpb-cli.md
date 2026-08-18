# lpb CLI Reference

The `lpb` launcher is the user-facing CLI for the LocalPibox devstack.
It wraps **podman** (or docker) to manage the devstack container lifecycle,
image resolution, and self-update.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/lpb-stack/devstack/main/scripts/install.sh | sudo bash
```

Installs two binaries to `/usr/local/bin/`:
- `lpb` — bash wrapper
- `lpb.py` — Python engine (stdlib-only, no external deps)

## Commands

| Command | Description |
|---|---|
| `lpb /path/to/project` | Start devstack with project mounted at `/workspace` |
| `lpb` (no args) | Show welcome screen, user picks project |
| `lpb --help` | Show help |
| `lpb --version` | Show installed lpb version |

## Image Selection

lpb resolves images in this order:

1. **`--tag dev`** → `:dev-cli/web` (latest development build)
2. **`--tag main`** → `:main-cli/web` (latest stable build)
3. **`--tag <version>`** → `:0.0.x-cli/web` (pinned to a specific version)
4. **Default** → resolves from last-used version in `~/.lpb-stack/devstack/version`

Two image flavours:
- **`:cli`** — dev environment + Pi CLI agent
- **`:web`** — extends `:cli` with VSCodium server on port 3000

### Image resolution flow

```
User calls:  lpb --tag main /project

Step 1: resolve_cli_image("main") → "ghcr.io/lpb-stack/devstack:main-cli"
Step 2: resolve_web_image("main") → "ghcr.io/lpb-stack/devstack:main-web"
Step 3: podman pull ghcr.io/lpb-stack/devstack:main-cli  (if not cached)
Step 4: podman pull ghcr.io/lpb-stack/devstack:main-web  (if not cached)
Step 5: podman run --name lpb-stack --network host \
         -v /project:/workspace \
         -v ~/.lpb-stack/agent:/home/lpb/.pi/agent \
         ghcr.io/lpb-stack/devstack:main-web
```

## Configuration

lpb reads config from `~/.lpb-stack/devstack/`:

| File | Purpose |
|---|---|
| `version` | Last-used version (auto-updated) |
| `env` | User overrides (merged with lpb.conf.env) |

Config files (in priority order, highest → lowest):
1. Shell environment (`export LPB_...`)
2. `~/.lpb-stack/devstack/env` (user overrides)
3. `lpb.stack.env` (per-pipeline: dev/main)
4. `lpb.conf.env` (global defaults)

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LPB_VERSION` | from `version` file | Stack version to run |
| `LPB_TAG` | `dev` or `main` | Pipeline selector |
| `LPB_CONTAINER_NAME` | `lpb-stack` | Podman container name |
| `LPB_MODE` | `web` | Image flavour: `cli` or `web` |
| `LPB_RUNTIME` | `podman` | Container runtime: `podman` or `docker` |

## Self-Update

Running `lpb` with a newer version available on GitHub automatically fetches
the latest `lpb.py` and `lpb` wrapper from the `main` branch.

To update manually:
```bash
curl -fsSL https://raw.githubusercontent.com/lpb-stack/devstack/main/scripts/install.sh | sudo bash
```

## Container Management

Under the hood, lpb uses podman to manage a single container named `lpb-stack`:

- **`lpb run`** — creates and starts the container
- **`lpb stop`** — stops the container
- **`lpb remove`** — removes the stopped container
- **`lpb logs`** — follow container logs
- **`lpb exec`** — execute commands inside the running container

Container lifecycle:
1. First run: pulls images, starts container, shows welcome
2. Subsequent runs: checks container exists → stops it (if running) → starts fresh
3. Use `lpb stop` to stop without removing; use `lpb remove` to clean up

## Examples

```bash
# Start with a project (picks latest dev image)
lpb ~/projects/myapp

# Pin to a specific version
lpb --tag 0.0.54-lpb-dev ~/projects/myapp

# Use stable (main) pipeline
lpb --tag main ~/projects/myapp

# Run CLI mode only (no VSCodium)
LPB_MODE=cli lpb ~/projects/myapp

# Check what image version is resolved
lpb --version
```
