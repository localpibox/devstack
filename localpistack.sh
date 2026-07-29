#!/usr/bin/env bash
# localpistack — Start a devstack container for a project.
#
# Usage:
#   devstack /path/to/project          # Start for specific folder
#   cd /path/to/project && devstack .  # Start for current folder
#   devstack                           # Start for current folder
#
# Environment:
#   ED_PORT          — Editor port (default: 3000)
#   CONNECTION_TOKEN — VSCodium auth token (default: devsession)
#
# What it does:
#   1. Builds the devstack image (if needed)
#   2. Generates .pi/mcp.json from project's .mcp.json or uses default
#   3. Starts the container with workspace mounted
#   4. Prints URLs to access

set -euo pipefail

# --- Config ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
DEFAULT_MCP="${SCRIPT_DIR}/mcp.json"
CONTAINER_NAME="localpistack"
ED_PORT="${ED_PORT:-3000}"
TOKEN="${CONNECTION_TOKEN:-devsession}"

# Resolve project directory
PROJECT_DIR="${1:-.}"
if [[ "$PROJECT_DIR" != /* ]]; then
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
fi
ABS_PROJECT_DIR="$PROJECT_DIR"

# --- Detect available podman/docker ----------------------------------------
if command -v podman &>/dev/null; then
  DC="podman compose"
elif command -v docker &>/dev/null; then
  DC="docker compose"
else
  echo "ERROR: Neither podman nor docker found." >&2
  exit 1
fi

# --- Check if container is already running ---------------------------------
if $DC -f "$COMPOSE_FILE" -p "localpistack" ps --services --filter "status=running" 2>/dev/null | grep -q "localpistack"; then
  echo "==> Devstack already running (project: $ABS_PROJECT_DIR)"
  echo "    Editor: http://localhost:${ED_PORT}?tkn=${TOKEN}"
  echo "    To stop: $DC -f $COMPOSE_FILE -p localpistack down"
  exit 0
fi

# --- Generate MCP config ---------------------------------------------------
# Project-specific: .mcp.json in the workspace (if present)
# Fallback: default MCP template at .mcp.json
if [ -f "$ABS_PROJECT_DIR/.mcp.json" ]; then
  MCP_SRC="$ABS_PROJECT_DIR/.mcp.json"
  echo "==> Using project MCP config: .mcp.json"
else
  MCP_SRC="$DEFAULT_MCP"
  echo "==> Using default MCP config: .mcp.json"
fi

echo "    Workspace: $ABS_PROJECT_DIR"
echo "    Editor:    :${ED_PORT}"

# --- Build image if needed -------------------------------------------------
echo ""
echo "==> Building image..."

IMAGE_EXISTS=$($DC -f "$COMPOSE_FILE" -p "localpistack" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
  | grep -c "^localpistack:latest$" || true)

if [ "$IMAGE_EXISTS" -gt 0 ]; then
  echo "    Image exists."
else
  echo "    Building (first run, may take a while)..."
  $DC -f "$COMPOSE_FILE" -p "localpistack" build --pull 2>&1 | tail -15
fi

# --- Start container -------------------------------------------------------
echo ""
echo "==> Starting localpistack..."

export WORKSPACE_DIR="$ABS_PROJECT_DIR"
$DC -f "$COMPOSE_FILE" -p "localpistack" up -d 2>&1 | tail -5

# Wait for VSCodium to be ready
echo ""
echo "==> Waiting for editor to start..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null "http://localhost:${ED_PORT}"; then
    break
  fi
  sleep 1
done

# --- Done! -----------------------------------------------------------------
echo ""
echo "    ╔══════════════════════════════════════════════════════╗"
echo "    ║  Devstack is ready!                                 ║"
echo "    ║                                                     ║"
echo "    ║  Editor:  http://localhost:${ED_PORT}?tkn=${TOKEN}  ║"
echo "    ║                                                     ║"
echo '    ║  Chat:    Pi Code GUI in the activity bar (🤖 icon) ║'
echo '    ║  Alt:     Terminal → run "pi" for full TUI          ║'
echo "    ╚══════════════════════════════════════════════════════╝"
echo ""
echo "    Stop: $DC -f $COMPOSE_FILE -p localpistack down"
echo "    Logs: $DC -f $COMPOSE_FILE -p localpistack logs -f"
