# LocalPibox Devstack — Quick Start

## Pull the image

```bash
# Pull latest image from GHCR
podman pull ghcr.io/localpibox/devstack:latest
```

## Run with a project folder

```bash
# Navigate to your project
cd ~/projects/myproject

# Launch devstack for this project
lpb /home/user/projects/myproject
```

### With options

```bash
# Custom editor port
lpb /path/to/project --port 8080

# LAN access with custom token
lpb /path/to/project --host 0.0.0.0 --token mysecret
```

### Using lpb.py directly (local dev)

```bash
# From the devstack directory
cd ~/devstack/localpibox/devstack
python3 scripts/lpb.py /path/to/project --port 8080
```

### Manual podman command (without lpb)

```bash
PROJECT_NAME=myproject
PROJECT_DIR=/home/user/projects/myproject
STATE_DIR=$HOME/.localpibox/state
BROWSER_DIR=$HOME/.localpibox/agent-browser

podman run -d \
    --name localpibox \
    --network host \
    --userns keep-id \
    -e LPB_ED_PORT=3000 \
    -e LPB_EDITOR_HOST=0.0.0.0 \
    -e LPB_DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace/$PROJECT_NAME" \
    -e LPB_CONNECTION_TOKEN=devsession \
    -e LPB_EXA_API_KEY=your-exa-key \
    -v "$PROJECT_DIR:/home/dev/workspace/$PROJECT_NAME:Z" \
    -v "$STATE_DIR:/home/dev/.pi:Z" \
    -v "$BROWSER_DIR:/home/dev/.agent-browser:Z" \
    ghcr.io/localpibox/devstack:latest
```

## Install lpb system-wide

```bash
# Download and install to ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/localpibox/devstack/main/scripts/install.sh | bash
```

## Update extensions (no rebuild)

```bash
# Update extensions to latest release (installs missing, upgrades stale)
podman exec -it localpibox pi update --extensions
```

## Useful commands

```bash
# View logs
podman logs -f localpibox

# Stop container
lpb --stop

# Remove container + state
lpb --remove

# Open browser to editor
xdg-open http://localhost:3000
```

## Architecture

```
Host:  ~/projects/myproject/    → Container: /home/dev/workspace/myproject/
Host:  ~/.localpibox/state/     → Container: /home/dev/.pi/
Host:  (Lemonade on host)       → Container: http://127.0.0.1:13305 (via --network host)
```

Tools see `myproject` as the project name, not `workspace`.

## CI/CD

- **Built on**: GitHub Actions (fast connection)
- **Published to**: `ghcr.io/localpibox/devstack:latest`
- **Triggers**: push to main, weekly cron, manual
- **Extension updates**: `pi update --extensions` (no rebuild needed)
