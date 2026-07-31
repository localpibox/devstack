#!/usr/bin/env bash
# /opt/devstack/start.sh — Container entrypoint
#
# This script:
# 1. Runs first-run bootstrap (volume ownership, directories)
# 2. Ensures extensions are installed (via update.sh --extensions)
# 3. Starts VSCodium server
# 4. Waits for readiness
# 5. Hands off to user command or starts shell
#
# Usage:
#   podman run -it --network host --userns keep-id \
#     -v /path/to/project:/home/dev/workspace/<project-name>:Z \
#     ghcr.io/localpibox/devstack:latest
#
# Environment variables:
#   LPB_ED_PORT              — Editor port (default: 3000)
#   LPB_DEVCONTAINER_WORKSPACE_DIR — Workspace directory
#   LPB_EDITOR_HOST          — Bind host for VSCodium server (default: 0.0.0.0)
#   LPB_CONNECTION_TOKEN     — VSCodium connection token
#
# Inside the container, these commands are available:
#   pi              — Start Pi CLI
#   stack.sh update — Update extensions/patches
#   exit            — Stop and exit

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
export PATH="/opt/vscodium/bin:/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"

# ── Default workspace and home directories ──────────────────────────────────
export HOME_DIR=/home/dev
export LPB_DEVCONTAINER_WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-/home/dev/workspace}"
export WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"

export LPB_LEMONADE_BASE_URL="${LPB_LEMONADE_BASE_URL:-http://127.0.0.1:13305/v1}"
export LPB_OPENROUTER_BASE_URL="${LPB_OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}"
export LPB_PI_SUPPORT_DIR="${LPB_PI_SUPPORT_DIR:-/opt/pi-support}"
export LPB_CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN:-devsession}"
export LPB_EDITOR_HOST="${LPB_EDITOR_HOST:-0.0.0.0}"
export LPB_ED_PORT="${LPB_ED_PORT:-3000}"

# Backwards-compat aliases (used by scripts that may reference old names)
export ED_PORT="${LPB_ED_PORT}"
export HOST="${LPB_EDITOR_HOST}"
export CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN}"
export DEVCONTAINER_WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"
export LEMONADE_BASE_URL="${LPB_LEMONADE_BASE_URL}"
export PI_SUPPORT_DIR="${LPB_PI_SUPPORT_DIR}"

# ── Load .env from workspace (LPB_ prefixed vars) ──────────────────────────
WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"
if [ -f "${WORKSPACE_DIR}/.env" ]; then
    echo "[devstack] Loading environment from ${WORKSPACE_DIR}/.env"
    set -a
    source "${WORKSPACE_DIR}/.env"
    set +a
else
    echo "[devstack] No .env found at ${WORKSPACE_DIR}/.env — using defaults"
fi

# ── Auto-detect mounted project subfolder when LPB_DEVCONTAINER_WORKSPACE_DIR not set ──
if [ -z "${LPB_DEVCONTAINER_WORKSPACE_DIR:+set}" ]; then
    subdir="$(find /home/dev/workspace -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)"
    if [ -n "$subdir" ]; then
        WORKSPACE_DIR="$subdir"
    fi
fi

SLEEP_INTERVAL=2
MAX_RETRIES=30

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
             "${HOME_DIR}/.pi/agent/git"

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

    # Copy config from repo (volume may have overwritten build-time copies)
    if [ -d /home/dev/.local/pi-config ]; then
        echo "[devstack] Syncing config from /home/dev/.local/pi-config/..."
        [ -f /home/dev/.local/pi-config/settings.json ] && cp /home/dev/.local/pi-config/settings.json /home/dev/.pi/agent/ 2>/dev/null
        [ -f /home/dev/.local/pi-config/mcp.json ] && cp /home/dev/.local/pi-config/mcp.json /home/dev/.pi/agent/mcp.json 2>/dev/null && sed -i 's/"directTools": true/"directTools": false/' /home/dev/.pi/agent/mcp.json
        [ -f /home/dev/.local/pi-config/AGENTS.md ] && cp /home/dev/.local/pi-config/AGENTS.md /home/dev/.pi/agent/ 2>/dev/null
        [ -d /home/dev/.local/pi-config/skills ] && cp -r /home/dev/.local/pi-config/skills/* /home/dev/.pi/agent/skills/ 2>/dev/null || true
        [ -d /home/dev/.local/pi-config/agents ] && cp /home/dev/.local/pi-config/agents/* /home/dev/.pi/agent/agents/ 2>/dev/null || true
        echo "[devstack] Config synced."
    fi

    # Create initialization marker
    touch "${HOME_DIR}/.pi/.initialized"
    echo "[devstack] First run bootstrap complete."
fi

# ── Ensure extensions are installed (via pi) ───────────────────────────────
# Uses the container's update.sh which checks via `pi list --json` and
# installs missing extensions via `pi install`. Runs on every boot.
echo "[devstack] Ensuring extensions are installed..."
if [ -f /opt/pi-patches/update.sh ]; then
    /opt/pi-patches/update.sh --extensions 2>&1 || echo "[devstack] WARN: extension install had warnings"
else
    echo "[devstack] WARN: /opt/pi-patches/update.sh not found — skipping extension install"
fi

# ── Post-initialization: native modules ─────────────────────────────────────
# Docker build compiles native modules for x86_64. At runtime they may be
# missing or incompatible. This installs build deps and recompiles
# better-sqlite3 from source if the .node binary is missing.
echo "[devstack] Post-init: checking native modules..."

NEED_REBUILD=false
EXT_BASE="${HOME_DIR}/.pi/agent/git"
for ext in "${EXT_BASE}"/*/*/; do
    [ -d "$ext/node_modules" ] || continue
    if [ -f "$ext/package.json" ] && grep -q better-sqlite3 "$ext/package.json" 2>/dev/null; then
        if [ ! -f "$ext/node_modules/better-sqlite3/build/Release/better_sqlite3.node" ]; then
            NEED_REBUILD=true
            break
        fi
    fi
done

if [ "$NEED_REBUILD" = "true" ]; then
    echo "[devstack] Recompile native modules (better-sqlite3) for this architecture..."
    for ext in "${EXT_BASE}"/*/*/; do
        [ -f "$ext/package.json" ] || continue
        if grep -q better-sqlite3 "$ext/package.json" 2>/dev/null; then
            echo "[devstack] Rebuilding native module: $(basename "$(dirname "$ext")")..."
            (cd "$ext" && npm rebuild better-sqlite3 2>&1 | tail -2) || \
            echo "[devstack] WARN: rebuild failed for $(basename "$(dirname "$ext")")"
        fi
    done
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
    --connection-token "${CONNECTION_TOKEN:-devsession}" \
    --default-folder "${WORKSPACE_DIR}" &

SERVER_PID=$!
echo "[devstack] Server PID: ${SERVER_PID}"

# ── Wait for readiness ─────────────────────────────────────────────────────

echo "[devstack] Waiting for server to be ready..."
for i in $(seq 1 ${MAX_RETRIES}); do
    if curl -sf "http://localhost:${ED_PORT}/?tkn=${CONNECTION_TOKEN:-devsession}" >/dev/null 2>&1; then
        # Build the connection URL with the configured token
        local_conn="http://localhost:${ED_PORT}/?tkn=${CONNECTION_TOKEN:-devsession}"
        if [ "${HOST:-0.0.0.0}" = "0.0.0.0" ]; then
            # Get LAN IP for additional access info
            lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
            if [ -n "$lan_ip" ]; then
                local_conn="http://${lan_ip}:${ED_PORT}/?tkn=${CONNECTION_TOKEN:-devsession} (LAN)"
            fi
        fi
        echo ""
        echo "╔═══════════════════════════════════════════════════════════╗"
        echo "║  LocalPibox Devstack                                      ║"
        echo "║  ╔═══════════════════════════════════════════════════════╗║"
        echo "║  ║  Editor:    ${local_conn}                      ║║"
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
