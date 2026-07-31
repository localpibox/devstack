#!/usr/bin/env bash
# localpistack — Start a devstack container for a project.
#
# Usage:
#   devstack /path/to/project          # Start for specific folder
#   cd /path/to/project && devstack .  # Start for current folder
#   devstack                           # Start for current folder
#
# Environment:
#   LPB_ED_PORT          — Editor port (default: 3000)
#   LPB_CONNECTION_TOKEN — VSCodium auth token (default: devsession)
#
# What it does:
#   1. Builds the devstack image (if needed)
#   2. Starts the container with workspace mounted
#   3. Prints URLs to access

set -euo pipefail

# --- Config ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="localpistack"
DEFAULT_STATE_DIR="${HOME}/.localpibox/state"
DEFAULT_BROWSER_DIR="${HOME}/.localpibox/agent-browser"

# Resolve project directory
PROJECT_DIR="${1:-.}"
if [[ "$PROJECT_DIR" != /* ]]; then
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
fi
ABS_PROJECT_DIR="$PROJECT_DIR"

# --- Detect available podman/docker ----------------------------------------
if command -v podman &>/dev/null; then
  DCMD="podman"
elif command -v docker &>/dev/null; then
  DCMD="docker"
else
  echo "ERROR: Neither podman nor docker found." >&2
  exit 1
fi

IMAGE_NAME="ghcr.io/localpibox/devstack:latest"
LPB_ED_PORT="${LPB_ED_PORT:-3000}"
LPB_CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN:-devsession}"
TOKEN="${LPB_CONNECTION_TOKEN}"

# --- Check if container is already running ---------------------------------
if $DCMD ps --format '{{.Names}}' 2>/dev/null | grep -q "$CONTAINER_NAME"; then
  echo "==> Devstack already running (project: $ABS_PROJECT_DIR)"
  echo "    Editor: http://localhost:${LPB_ED_PORT}?tkn=${TOKEN}"
  echo "    To stop: $DCMD stop $CONTAINER_NAME"
  exit 0
fi

# --- Build image if needed -------------------------------------------------
echo "==> Building image..."

IMAGE_EXISTS=$($DCMD images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
  | grep -c "^ghcr.io/localpibox/devstack:latest$" || true)

if [ "$IMAGE_EXISTS" -gt 0 ]; then
  echo "    Image exists."
else
  echo "    Building (first run, may take a while)..."
  cd "$SCRIPT_DIR"
  $DCMD build -t "$IMAGE_NAME" . 2>&1 | tail -10
  cd -
fi

# --- Ensure state directories exist ────────────────────────────────────────
mkdir -p "$DEFAULT_STATE_DIR" "$DEFAULT_BROWSER_DIR"

# --- Start container ──────────────────────────────────────────────────────
echo ""
echo "==> Starting $CONTAINER_NAME..."

$DCMD run -d \
    --name "$CONTAINER_NAME" \
    --network host \
    --userns keep-id \
    -e LPB_ED_PORT="$LPB_ED_PORT" \
    -e LPB_EDITOR_HOST=0.0.0.0 \
    -e LPB_CONNECTION_TOKEN="$TOKEN" \
    -e LPB_DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace/$(basename "$ABS_PROJECT_DIR")" \
    -v "$ABS_PROJECT_DIR:/home/dev/workspace/$(basename "$ABS_PROJECT_DIR"):Z" \
    -v "$DEFAULT_STATE_DIR:/home/dev/.pi:Z" \
    -v "$DEFAULT_BROWSER_DIR:/home/dev/.agent-browser:Z" \
    "$IMAGE_NAME"

# Wait for VSCodium to be ready
echo ""
echo "==> Waiting for editor to start..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null "http://localhost:${LPB_ED_PORT}" 2>/dev/null; then
    break
  fi
  sleep 1
done

# --- Done! -----------------------------------------------------------------
echo ""
echo "    ╔══════════════════════════════════════════════════════╗"
echo "    ║  Devstack is ready!                                 ║"
echo "    ║                                                     ║"
echo "    ║  Editor:  http://localhost:${LPB_ED_PORT}?tkn=${TOKEN}  ║"
echo "    ║                                                     ║"
echo '    ║  Chat:    Pi Code GUI in the activity bar (🤖 icon) ║'
echo '    ║  Alt:     Terminal → run "pi" for full TUI          ║'
echo "    ╚══════════════════════════════════════════════════════╝"
echo ""
echo "    Stop: $DCMD stop $CONTAINER_NAME"
echo "    Logs: $DCMD logs -f $CONTAINER_NAME"
