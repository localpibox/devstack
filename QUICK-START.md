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
./run.sh /home/user/projects/myproject
```

### With options

```bash
# Custom editor port
./run.sh /path/to/project --port 8080

# Pull latest image first
./run.sh /path/to/project --pull --port 3000
```

### Manual podman command (without run.sh)

```bash
PROJECT_NAME=myproject
PROJECT_DIR=/home/user/projects/myproject
STATE_DIR=$HOME/.localpibox/devstack-state

podman run -d \
    --name localpibox \
    --network host \
    --userns keep-id \
    -e ED_PORT=3000 \
    -v "$PROJECT_DIR:/home/dev/workspace/$PROJECT_NAME:Z" \
    -v "$STATE_DIR:/home/dev/.pi:Z" \
    -v "$HOME/.config/podman:/home/dev/.config/containers:Z" \
    ghcr.io/localpibox/devstack:latest
```

## Update extensions/patches (no rebuild)

```bash
# Pull latest tarballs from GHCR and load
./stack.sh update --pull

# Update only extensions
./stack.sh update --extensions

# Update only patches
./stack.sh update --patches
```

## Useful commands

```bash
# View logs
podman logs -f localpibox

# Stop container
podman stop localpibox

# Remove container
podman rm localpibox

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
- **Update tarballs**: built separately, loaded without rebuild
