#!/usr/bin/env bash
# /opt/devstack/entrypoint-cli.sh — Container entrypoint for CLI image
#
# This script:
# 1. Runs first-run bootstrap (volume ownership, directories)
# 2. Ensures extensions are installed (via update.sh --extensions)
# 3. Starts Pi CLI (foreground)
# 4. When pi exits, stops the container cleanly
#
# Usage:
#   podman run -it --network host --userns keep-id \
#     -v /path/to/project:/home/dev/workspace/<project-name>:Z \
#     ghcr.io/localpibox/devstack:cli
#
# Environment variables:
#   LPB_DEVCONTAINER_WORKSPACE_DIR — Workspace directory (default: /home/dev/workspace)
#   LPB_STATE_DIR                  — Pi state dir (default: /home/dev/.pi)
#   LPB_EXA_API_KEY                — Exa MCP key
#   LPB_LEMONADE_BASE_URL          — Local LLM base URL
#   LPB_OPENROUTER_BASE_URL        — OpenRouter base URL

set -euo pipefail

export PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"
export HOME_DIR=/home/dev
export LPB_DEVCONTAINER_WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-/home/dev/workspace}"
export WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"

export LEMONADE_BASE_URL="${LPB_LEMONADE_BASE_URL:-${LEMONADE_BASE_URL:-http://127.0.0.1:13305/v1}}"
export OPENROUTER_BASE_URL="${LPB_OPENROUTER_BASE_URL:-${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}}"
export PI_SUPPORT_DIR="${LPB_PI_SUPPORT_DIR:-${PI_SUPPORT_DIR:-/opt/pi-support}}"

# ── Load .env from workspace (filtered to LPB_* vars) ───────────────────────
ENV_FILE=""
if [ -f "${WORKSPACE_DIR}/.env" ]; then
    ENV_FILE="${WORKSPACE_DIR}/.env"
fi

if [ -n "$ENV_FILE" ]; then
    echo "[devstack] Loading environment from ${ENV_FILE}"
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        case "$key" in
            LPB_*)
                export "$key"="$value"
                stripped="${key#LPB_}"
                export "$stripped"="$value"
                ;;
        esac
    done < "$ENV_FILE"
fi

export EXA_API_KEY="${LPB_EXA_API_KEY:-${EXA_API_KEY:-}}"

# ── First-run bootstrap ────────────────────────────────────────────────────
FIRST_RUN=false
if [ ! -f "${HOME_DIR}/.pi/.initialized" ]; then
    FIRST_RUN=true
    echo "[devstack] First run detected — bootstrapping..."
fi

if [ "$FIRST_RUN" = "true" ]; then
    echo "[devstack] Fixing volume ownership..."
    chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true
    chmod -R u+rwX "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true

    mkdir -p "${HOME_DIR}/.pi/agent/mcp" \
             "${HOME_DIR}/.pi/agent/skills" \
             "${HOME_DIR}/.venvs" \
             "${HOME_DIR}/.pi/agent/git"

    npm config set prefix '/home/dev/.npm-global' 2>/dev/null || true
    mkdir -p /home/dev/.npm-global/bin /home/dev/.npm-global/lib/node_modules 2>/dev/null || true
    chown -R "$(id -u):$(id -g)" /home/dev/.npm-global 2>/dev/null || true
    npm config set fetch-retries 5 2>/dev/null || true
    npm config set fetch-retry-mintimeout 20000 2>/dev/null || true
    npm config set fetch-retry-maxtimeout 120000 2>/dev/null || true
    npm config set progress false 2>/dev/null || true
    npm config set allow-git all 2>/dev/null || true
    npm config set allow-scripts '{"agent-browser":true,"better-sqlite3":true,"protobufjs":true,"esbuild":true,"@google/genai":true}' 2>/dev/null || true

    if [ -d /home/dev/.local/pi-config ]; then
        echo "[devstack] Syncing config from /home/dev/.local/pi-config/..."
        [ -f /home/dev/.local/pi-config/settings.json ] && cp /home/dev/.local/pi-config/settings.json /home/dev/.pi/agent/ 2>/dev/null
        [ -f /home/dev/.local/pi-config/mcp.json ] && cp /home/dev/.local/pi-config/mcp.json /home/dev/.pi/agent/mcp.json 2>/dev/null
        [ -f /home/dev/.local/pi-config/AGENTS.md ] && cp /home/dev/.local/pi-config/AGENTS.md /home/dev/.pi/agent/ 2>/dev/null
        [ -d /home/dev/.local/pi-config/skills ] && cp -r /home/dev/.local/pi-config/skills/* /home/dev/.pi/agent/skills/ 2>/dev/null || true
        [ -d /home/dev/.local/pi-config/agents ] && cp /home/dev/.local/pi-config/agents/* /home/dev/.pi/agent/agents/ 2>/dev/null || true
        echo "[devstack] Config synced."
    fi

    touch "${HOME_DIR}/.pi/.initialized"
    echo "[devstack] First run bootstrap complete."
fi

# ── Post-initialization: native modules ─────────────────────────────────────
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

# ── Extensions (deferred to runtime) ───────────────────────────────────────
echo "[devstack] Extensions managed by: pi update --extensions"

# ── Workspace info ──────────────────────────────────────────────────────────
if [ ! -d "${WORKSPACE_DIR}" ]; then
    echo "[devstack] WARNING: Workspace does not exist: ${WORKSPACE_DIR}"
elif [ -z "$(ls -A "${WORKSPACE_DIR}" 2>/dev/null)" ]; then
    echo "[devstack] WARNING: Workspace is empty: ${WORKSPACE_DIR}"
else
    file_count=$(find "${WORKSPACE_DIR}" -maxdepth 1 -type f | wc -l)
    echo "[devstack] Workspace: ${WORKSPACE_DIR} (${file_count} files)"
fi

# ── Start Pi CLI (foreground, stops container on exit) ─────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  LocalPibox Devstack — Pi CLI                            ║"
echo "║  Workspace: ${WORKSPACE_DIR}                ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "  pi              — Start Pi CLI session"
echo "  exit            — Stop container"
echo ""

# Run pi in foreground. When pi exits, exec the container stop.
pi "$@"
EXIT_CODE=$?

echo ""
echo "[devstack] Pi session exited (code: ${EXIT_CODE}). Stopping container..."
exit $EXIT_CODE
