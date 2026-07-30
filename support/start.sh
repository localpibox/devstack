#!/usr/bin/env bash
# /opt/devstack/start.sh — Container entrypoint
#
# This script:
# 1. Runs first-run bootstrap (volume ownership, directories, extension install)
# 2. Starts VSCodium server
# 3. Waits for readiness
# 4. Hands off to user command or starts shell
#
# Usage:
#   podman run -it --network host --userns keep-id \
#     -v /path/to/project:/home/dev/workspace/myproject:Z \
#     ghcr.io/localpibox/devstack:latest
#
# Environment variables:
#   ED_PORT            — Editor port (default: 3000)
#   DEVCONTAINER_WORKSPACE_DIR — Workspace directory
#   LEMONADE_BASE_URL  — Lemonade API base URL
#   PI_SUPPORT_DIR     — Pi support tools directory
#   HOST               — Bind host for VSCodium server (default: 0.0.0.0)
#
# Inside the container, these commands are available:
#   pi              — Start Pi CLI
#   stack.sh update — Update extensions/patches
#   exit            — Stop and exit

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
export PATH="/opt/vscodium/bin:${PATH}"
WORKSPACE_DIR="${DEVCONTAINER_WORKSPACE_DIR:-/home/dev/workspace}"
HOME_DIR=/home/dev
LEMONADE_BASE_URL="${LEMONADE_BASE_URL:-http://127.0.0.1:13305/v1}"
PI_SUPPORT_DIR="${PI_SUPPORT_DIR:-/opt/pi-support}"
ED_PORT="${ED_PORT:-3000}"
HOST="${HOST:-0.0.0.0}"
SLEEP_INTERVAL=2
MAX_RETRIES=30

# Auto-detect mounted project subfolder when DEVCONTAINER_WORKSPACE_DIR not set
if [ -z "${DEVCONTAINER_WORKSPACE_DIR:-}" ]; then
    subdir="$(find /home/dev/workspace -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)"
    if [ -n "$subdir" ]; then
        WORKSPACE_DIR="$subdir"
    fi
fi

# ── First-run bootstrap ────────────────────────────────────────────────────

FIRST_RUN=false
if [ ! -f "${HOME_DIR}/.pi/.initialized" ]; then
    FIRST_RUN=true
    echo "[devstack] First run detected — bootstrapping..."
fi

if [ "$FIRST_RUN" = "true" ]; then
    # Fix volume ownership
    echo "[devstack] Fixing volume ownership..."
    chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true
    chmod -R u+rwX "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true
    chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.config/codium" 2>/dev/null || true

    # Create required directories
    mkdir -p "${HOME_DIR}/.pi/agent/mcp" \
             "${HOME_DIR}/.pi/agent/skills" \
             "${HOME_DIR}/.venvs" \
             "${HOME_DIR}/.pi/agent/git" \
             "${HOME_DIR}/.pi/agent/npm"

    # NPM config
    npm config set prefix '/home/dev/.npm-global' 2>/dev/null || true
    mkdir -p /home/dev/.npm-global/bin /home/dev/.npm-global/lib/node_modules 2>/dev/null || true
    chown -R "$(id -u):$(id -g)" /home/dev/.npm-global 2>/dev/null || true
    npm config set fetch-retries 5 2>/dev/null || true
    npm config set fetch-retry-mintimeout 20000 2>/dev/null || true
    npm config set fetch-retry-maxtimeout 120000 2>/dev/null || true
    npm config set progress false 2>/dev/null || true
    npm config set allow-git all 2>/dev/null || true
    npm config set allow-scripts '{"agent-browser":true,"better-sqlite3":true,"protobufjs":true,"esbuild":true,"@google/genai":true}' 2>/dev/null || true

    # Copy default config if completely clean (no settings.json)
    if [ ! -f "${HOME_DIR}/.pi/agent/settings.json" ]; then
        if [ -f /home/dev/.local/pi-config/settings.json ]; then
            mkdir -p "${HOME_DIR}/.pi/agent"
            cp /home/dev/.local/pi-config/settings.json "${HOME_DIR}/.pi/agent/settings.json" 2>/dev/null || true
            [ -f /home/dev/.local/pi-config/mcp.json ] && cp /home/dev/.local/pi-config/mcp.json "${HOME_DIR}/.pi/agent/" 2>/dev/null || true
            [ -f /home/dev/.local/pi-config/models.json ] && cp /home/dev/.local/pi-config/models.json "${HOME_DIR}/.pi/agent/" 2>/dev/null || true
            [ -f /home/dev/.local/pi-config/AGENTS.md ] && cp /home/dev/.local/pi-config/AGENTS.md "${HOME_DIR}/.pi/agent/" 2>/dev/null || true
        fi
    fi

    # Inject default extension packages if settings.json has none
    HAS_PACKAGES=$(jq -r 'has("packages")' "${HOME_DIR}/.pi/agent/settings.json" 2>/dev/null || echo false)
    if [ "$HAS_PACKAGES" = "false" ]; then
        echo "[devstack] Injecting default extension packages into settings.json..."
        jq '.packages = [
            "git:github.com/localpibox/lemonade-pi-plugin@patches/qwen-vision",
            "git:github.com/localpibox/pi-hermes-memory@fix/subprocess-provider",
            "npm:pi-mcp-adapter",
            "npm:@tintinweb/pi-subagents",
            "npm:pi-powerline-footer"
        ]' "${HOME_DIR}/.pi/agent/settings.json" > "${HOME_DIR}/.pi/agent/settings.json.tmp" 2>/dev/null && \
            mv "${HOME_DIR}/.pi/agent/settings.json.tmp" "${HOME_DIR}/.pi/agent/settings.json" && \
            chown "$(id -u):$(id -g)" "${HOME_DIR}/.pi/agent/settings.json" || true
    fi

    # Create initialization marker
    touch "${HOME_DIR}/.pi/.initialized"
    echo "[devstack] First run bootstrap complete."
fi

# ── Ensure extensions are installed (runs on every boot) ──
if [ -f "${HOME_DIR}/.pi/agent/settings.json" ]; then
    echo "[devstack] Validating extension installation..."
    while IFS= read -r ext_entry; do
        ext_entry="$(echo "$ext_entry" | tr -d '"' | tr -d ' ')"
        [ -z "$ext_entry" ] && continue
        case "$ext_entry" in
            git:https://*)
                rel_path="${ext_entry#git:}"
                rel_path="${rel_path#*://}"
                ;;
            git://*)
                rel_path="${ext_entry#git:}"
                rel_path="${rel_path#*://}"
                ;;
            git:*)
                rel_path="${ext_entry#git:}"
                ;;
            *) continue ;;
        esac
        # Remove branch/tag suffix (e.g. @patches/qwen-vision, #abc123)
        path_only="${rel_path%%[@#]*}"
        check_dir="${HOME_DIR}/.pi/agent/git/${path_only}"
        if [ ! -d "$check_dir" ]; then
            echo "[devstack] Installing missing extension: $ext_entry"
            pi install "$ext_entry" 2>&1 || echo "[devstack] WARN: extension install failed: $ext_entry"
        fi
    done < <(jq -r '.packages[]?' "${HOME_DIR}/.pi/agent/settings.json" 2>/dev/null)
fi

# ── Start VSCodium server ──────────────────────────────────────────────────

echo "[devstack] Starting VSCodium server on port ${ED_PORT}..."

# Kill any existing server
pkill -f "vscodium-server" 2>/dev/null || true
sleep 1

# Start the server in the background (bind to all interfaces by default)
/opt/vscodium/bin/codium-server serve-web \
    --accept-server-license-terms \
    --host "${HOST}" \
    --port "${ED_PORT}" \
    --connection-token devsession \
    --default-folder "${WORKSPACE_DIR}" &

SERVER_PID=$!
echo "[devstack] Server PID: ${SERVER_PID}"

# ── Wait for readiness ─────────────────────────────────────────────────────

echo "[devstack] Waiting for server to be ready..."
for i in $(seq 1 ${MAX_RETRIES}); do
    if curl -sf "http://localhost:${ED_PORT}/health" >/dev/null 2>&1; then
        echo ""
        echo "╔═══════════════════════════════════════════════════════════╗"
        echo "║  LocalPibox Devstack                                      ║"
        echo "║  ╔═══════════════════════════════════════════════════════╗║"
        echo "║  ║  Editor:    http://localhost:${ED_PORT}                ║║"
        echo "║  ║  Token:     devsession                                 ║║"
        echo "║  ║  Workspace: ${WORKSPACE_DIR}                  ║║"
        echo "║  ╚═══════════════════════════════════════════════════════╝║"
        echo "╚═══════════════════════════════════════════════════════════╝"
        echo ""
        echo "  Available commands:"
        echo "    pi              — Start Pi CLI"
        echo "    stack.sh update — Update extensions/patches"
        echo "    exit            — Stop the server and exit"
        echo ""
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "[devstack] ⚠ Server may not be ready yet"
    fi
    sleep ${SLEEP_INTERVAL}
done

# ── Run user command or start shell ─────────────────────────────────────────

if [ $# -gt 0 ]; then
    exec "$@"
else
    exec /bin/bash
fi
