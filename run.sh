#!/usr/bin/env bash
# run.sh — Launch LocalPibox devstack for a project
#
# Usage:
#   ./run.sh /path/to/project          # Run with defaults
#   ./run.sh /path/to/project --port 8080   # Custom editor port
#   ./run.sh /path/to/project --pull    # Pull latest image first
#   ./run.sh --help
#
# Mount structure:
#   Host: $PROJECT → Container: /home/dev/workspace/<project-name>/
#   Host: ~/.localpibox/ → Container: /home/dev/.localpibox/
#
# Environment: reads LPB_* vars from project's .env file

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
IMAGE_NAME="${IMAGE_NAME:-ghcr.io/localpibox/devstack:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-localpibox}"
DEFAULT_PORT=3000
DEFAULT_STATE_DIR="${HOME}/.localpibox/state"
DEFAULT_BROWSER_DIR="${HOME}/.localpibox/agent-browser"

# ── Container backend ──────────────────────────────────────────────────────
CONTAINER_CMD="${CONTAINER_CMD:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo podman)}"

# ── Parse args ─────────────────────────────────────────────────────────────

PROJECT_DIR=""
ED_PORT="$DEFAULT_PORT"
PULL=false
COMMANDS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --port|-p)
            ED_PORT="$2"; shift 2 ;;
        --pull)
            PULL=true; shift ;;
        --help|-h)
            cat <<EOF
LocalPibox Devstack Launcher

Usage: $0 [OPTIONS] <project-path>

Options:
  -p, --port PORT    Editor port (default: $DEFAULT_PORT)
  --pull             Pull latest image before running
  --help, -h         Show this help

Examples:
  $0 /home/user/myproject
  $0 /home/user/myproject --port 8080
  $0 /home/user/myproject --pull --port 3000
EOF
            exit 0 ;;
        --)
            shift; COMMANDS+=("$@"); break ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1 ;;
        *)
            if [ -z "$PROJECT_DIR" ]; then
                PROJECT_DIR="$1"
            else
                COMMANDS+=("$1")
            fi
            shift ;;
    esac
done

# ── Validate ────────────────────────────────────────────────────────────────

if [ -z "$PROJECT_DIR" ]; then
    echo "Error: project path required" >&2
    echo "Usage: $0 <project-path> [OPTIONS]" >&2
    exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: project directory not found: $PROJECT_DIR" >&2
    exit 1
fi

# Derive project name from directory basename
PROJECT_NAME=$(basename "$PROJECT_DIR")

# ── Load .env if present ────────────────────────────────────────────────────
# Sources LPB_* vars from .env file in project directory.
# These get passed as -e flags to the container.
LOAD_ENV=""
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "Loading .env from $PROJECT_DIR"
    LOAD_ENV="$PROJECT_DIR/.env"
fi

# ── Pull if requested ──────────────────────────────────────────────────────

if [ "$PULL" = true ]; then
    echo "Pulling $IMAGE_NAME..."
    $CONTAINER_CMD pull "$IMAGE_NAME"
fi

# ── Build podman run command ────────────────────────────────────────────────

echo -e "Starting LocalPibox devstack..."
echo "  Project:  $PROJECT_DIR → /home/dev/workspace/$PROJECT_NAME/"
echo "  State:    $DEFAULT_STATE_DIR → /home/dev/.pi/"
echo "  Browser:  $DEFAULT_BROWSER_DIR → /home/dev/.agent-browser/"
echo "  Editor:   http://localhost:$ED_PORT"
echo "  Image:    $IMAGE_NAME"
echo ""

# Ensure state directories exist
mkdir -p "$DEFAULT_STATE_DIR" "$DEFAULT_BROWSER_DIR"

# Run the container
$CONTAINER_CMD run -d \
    --name "$CONTAINER_NAME" \
    --network host \
    --userns keep-id \
    -e LPB_ED_PORT="$ED_PORT" \
    -e LPB_EDITOR_HOST=0.0.0.0 \
    -e LPB_DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace/$PROJECT_NAME" \
    -v "$PROJECT_DIR:/home/dev/workspace/$PROJECT_NAME:Z" \
    -v "$DEFAULT_STATE_DIR:/home/dev/.pi:Z" \
    -v "$DEFAULT_BROWSER_DIR:/home/dev/.agent-browser:Z" \
    "$IMAGE_NAME" &

# Wait for container to start and editor to be ready
echo "Waiting for editor to be ready..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$ED_PORT/health" >/dev/null 2>&1; then
        echo ""
        echo "✓ Devstack ready at http://localhost:$ED_PORT?tkn=devsession"
        echo ""
        echo "  Useful commands:"
        echo "    $CONTAINER_CMD logs -f $CONTAINER_NAME   # View logs"
        echo "    $CONTAINER_CMD exec -it $CONTAINER_NAME pi   # Start Pi CLI"
        echo "    $CONTAINER_CMD exec -it $CONTAINER_NAME /stack.sh update   # Update extensions"
        echo "    $CONTAINER_CMD stop $CONTAINER_NAME     # Stop the container"
        echo ""
        exit 0
    fi
    sleep 1
done

echo "⚠ Container is running but editor may not be ready yet."
echo "  Check logs: $CONTAINER_CMD logs $CONTAINER_NAME"
