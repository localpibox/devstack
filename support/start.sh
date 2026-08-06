#!/usr/bin/env bash
# start.sh — LocalPibox Devstack central configuration and startup
#
# This script is the single source of truth for:
#   1. Environment variable defaults (lowest precedence)
#   2. Loading .env from the project workspace
#   3. Loading LPB_* env vars from the container environment
#   4. First-run bootstrap (directories, config sync)
#   5. Executing the target command (pi for CLI, vscodium-server for web)
#
# Called by:
#   - entrypoint-cli.sh  → exec start.sh run --mode cli [args → pi]
#   - entrypoint-web.sh  → exec start.sh run --mode web [args → shell]
#
# Usage:
#   bash /opt/devstack/start.sh run --mode cli [additional args → pi]
#   bash /opt/devstack/start.sh run --mode web [additional args → shell]

set -euo pipefail

# ─── Logging helpers ─────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
debug() { [[ "${DEBUG:-}" != "true" ]] || echo "[DEBUG] $*"; }

# ─── 1. PARSE COMMAND-LINE ARGUMENTS ───────────────────────────────────────
MODE=""
EXTRA_ARGS=()

while (( $# )); do
    case "$1" in
        run)
            shift
            ;;
        --mode)
            MODE="${2:-}"
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$MODE" ]]; then
    echo "[ERROR] Mode not specified. Usage: start.sh run --mode {cli|web} [args]" >&2
    exit 1
fi

# ─── 0. LOAD RUNTIME DEFAULTS FROM lpb.conf.env ────────────────────────────
# lpb.conf.env provides baked-in runtime defaults (lowest precedence).
# Workspace .env (step 2) overrides these; shell env (step 3) overrides all.
# Bare names (no LPB_ prefix) take priority over LPB_ names.

_stack_conf="/opt/devstack/lpb.conf.env"
if [[ -f "${_stack_conf}" ]]; then
    debug "Loading runtime defaults from ${_stack_conf}"
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        [[ "$line" != *=* ]] && continue
        key=$(echo "$line" | cut -d= -f1 | xargs 2>/dev/null || echo "$line" | cut -d= -f1)
        value=$(echo "$line" | cut -d= -f2- | xargs 2>/dev/null || echo "$line" | cut -d= -f2-)
        export "$key"="$value"
        stripped="${key#LPB_}"
        if [[ -z "${!stripped+x}" ]]; then
            export "$stripped"="$value"
        fi
    done < "${_stack_conf}"
fi

# --- 0b. INLINE FALLBACK DEFAULTS (if lpb.conf.env is missing) ---
export HOME_DIR="/home/lpb"
export PATH="/home/lpb/.npm-global/bin:/home/lpb/.local/bin:${PATH}"

# -- Core paths --
export LPB_DEVCONTAINER_WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-/home/lpb/workspace}"
export PI_SUPPORT_DIR="${PI_SUPPORT_DIR:-/opt/pi-support}"

# -- API endpoints --
export LEMONADE_BASE_URL="${LPB_LEMONADE_BASE_URL:-${LEMONADE_BASE_URL:-http://127.0.0.1:13305/v1}}"
export OPENROUTER_BASE_URL="${LPB_OPENROUTER_BASE_URL:-${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}}"
export LPB_LEMONADE_BASE_URL="${LEMONADE_BASE_URL}"
export LPB_OPENROUTER_BASE_URL="${OPENROUTER_BASE_URL}"

# -- Editor (web mode) --
export LPB_ED_PORT="${LPB_ED_PORT:-${ED_PORT:-3000}}"
export LPB_EDITOR_HOST="${LPB_EDITOR_HOST:-${HOST:-0.0.0.0}}"
export LPB_CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN:-${CONNECTION_TOKEN:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null || echo "devsession")}}"

# Backwards-compat aliases (used by VSCodium server and other tools)
export ED_PORT="${LPB_ED_PORT}"
export HOST="${LPB_EDITOR_HOST}"
export CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN}"
export DEVCONTAINER_WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"

# -- Workspace --
WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"

# -- Context window / max tokens ratio --
export LPB_MAX_TOKENS_CONTEXT_RATIO="${LPB_MAX_TOKENS_CONTEXT_RATIO:-0.06}"
export MAX_TOKENS_CONTEXT_RATIO="${LPB_MAX_TOKENS_CONTEXT_RATIO}"


# ── Browser config ──
export LPB_AGENT_BROWSER_ARGS="${LPB_AGENT_BROWSER_ARGS:-}"
export LPB_AGENT_BROWSER_MAX_OUTPUT="${LPB_AGENT_BROWSER_MAX_OUTPUT:-4000}"
export LPB_AGENT_BROWSER_CONTENT_BOUNDARIES="${LPB_AGENT_BROWSER_CONTENT_BOUNDARIES:-true}"
export LPB_AGENT_BROWSER_CONFIRM_ACTIONS="${LPB_AGENT_BROWSER_CONFIRM_ACTIONS:-delete,download,cookie_delete,file_access}"
export LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS="${LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS:-300000}"
export LPB_AGENT_BROWSER_SESSION="${LPB_AGENT_BROWSER_SESSION:-${PI_WORKTREE_ID:-}}"

# ── Exa API key ──
export LPB_EXA_API_KEY="${LPB_EXA_API_KEY:-${EXA_API_KEY:-}}"
export EXA_API_KEY="${LPB_EXA_API_KEY}"

# ── Persistence flags ──
export LPB_PERSIST_GH_CONFIG="${LPB_PERSIST_GH_CONFIG:-true}"

debug "LEMONADE_BASE_URL=$LEMONADE_BASE_URL"
debug "WORKSPACE_DIR=$WORKSPACE_DIR"
debug "ED_PORT=$ED_PORT"
debug "EDITOR_HOST=$HOST"
debug "MAX_TOKENS_CONTEXT_RATIO=$MAX_TOKENS_CONTEXT_RATIO"

# ─── 2. LOAD .ENV FROM PROJECT WORKSPACE ─────────────────────────────────────
# Variables from the project's .env file (LPB_* prefix only) override defaults.

ENV_FILE=""
if [[ -f "${WORKSPACE_DIR}/.env" ]]; then
    ENV_FILE="${WORKSPACE_DIR}/.env"
    debug "Found .env at ${ENV_FILE}"
fi

if [[ -n "$ENV_FILE" ]]; then
    info "Loading environment from ${ENV_FILE}"
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        [[ "$key" != *=* ]] && continue
        key=$(echo "$key" | xargs 2>/dev/null || echo "$key")
        value=$(echo "$value" | xargs 2>/dev/null || echo "$value")
        case "$key" in
            LPB_*)
                export "$key"="$value"
                stripped="${key#LPB_}"
                export "$stripped"="$value"
                ;;
        esac
    done < "$ENV_FILE"
    # Re-read key values after .env load
    WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-$WORKSPACE_DIR}"
    export WORKSPACE_DIR
fi

# ─── 3. WORKSPACE INFO ──────────────────────────────────────────────────────

if [[ ! -d "${WORKSPACE_DIR}" ]]; then
    warn "Workspace path does not exist: ${WORKSPACE_DIR}"
    warn "  Mount: /home/lpb/workspace → ${WORKSPACE_DIR}"
elif [[ -z "$(ls -A "${WORKSPACE_DIR}" 2>/dev/null)" ]]; then
    warn "Workspace directory is empty: ${WORKSPACE_DIR}"
else
    file_count=$(find "${WORKSPACE_DIR}" -maxdepth 1 -type f 2>/dev/null | wc -l)
    info "Workspace: ${WORKSPACE_DIR} (${file_count} files)"
fi

# ─── 4. FIRST-RUN BOOTSTRAP ─────────────────────────────────────────────────

FIRST_RUN=false
if [[ ! -f "${HOME_DIR}/.pi/.initialized" ]]; then
    FIRST_RUN=true
    info "First run detected — bootstrapping..."
fi

if [[ "$FIRST_RUN" = "true" ]]; then
    info "Fixing volume ownership..."
    chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" "${HOME_DIR}/.config" 2>/dev/null || true
    chmod -R u+rwX "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true

    mkdir -p "${HOME_DIR}/.pi/agent/mcp" \
             "${HOME_DIR}/.pi/agent/skills" \
             "${HOME_DIR}/.pi/agent/git" \
             "${HOME_DIR}/.venvs"

    npm config set prefix '/home/lpb/.npm-global' 2>/dev/null || true
    mkdir -p /home/lpb/.npm-global/bin /home/lpb/.npm-global/lib/node_modules 2>/dev/null || true
    chown -R "$(id -u):$(id -g)" /home/lpb/.npm-global 2>/dev/null || true
    npm config set fetch-retries 5 2>/dev/null || true
    npm config set fetch-retry-mintimeout 20000 2>/dev/null || true
    npm config set fetch-retry-maxtimeout 120000 2>/dev/null || true
    npm config set progress false 2>/dev/null || true
    npm config set allow-git all 2>/dev/null || true
    npm config set allow-scripts 'better-sqlite3 agent-browser esbuild protobufjs @google/genai' 2>/dev/null || true

    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > /home/lpb/.npmrc 2>/dev/null || true
    mkdir -p "${HOME_DIR}/.pi/agent/git"
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > "${HOME_DIR}/.pi/agent/git/.npmrc" 2>/dev/null || true

    if [[ -d /home/lpb/.local/pi-config ]]; then
        info "Syncing config from /home/lpb/.local/pi-config/..."
        [[ -f /home/lpb/.local/pi-config/settings.json ]] && cp /home/lpb/.local/pi-config/settings.json /home/lpb/.pi/agent/ 2>/dev/null
        [[ -f /home/lpb/.local/pi-config/mcp.json ]] && cp /home/lpb/.local/pi-config/mcp.json /home/lpb/.pi/agent/mcp.json 2>/dev/null && sed -i 's/"directTools": true/"directTools": false/' /home/lpb/.pi/agent/mcp.json 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/AGENTS.md ]] && cp /home/lpb/.local/pi-config/AGENTS.md /home/lpb/.pi/agent/ 2>/dev/null
        [[ -f /home/lpb/.local/pi-config/SYSTEM.md ]] && cp /home/lpb/.local/pi-config/SYSTEM.md /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/APPEND_SYSTEM.md ]] && cp /home/lpb/.local/pi-config/APPEND_SYSTEM.md /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -d /home/lpb/.local/pi-config/skills ]] && cp -r /home/lpb/.local/pi-config/skills/* /home/lpb/.pi/agent/skills/ 2>/dev/null || true
        [[ -d /home/lpb/.local/pi-config/agents ]] && cp /home/lpb/.local/pi-config/agents/* /home/lpb/.pi/agent/agents/ 2>/dev/null || true
        info "Config synced."
    fi

    touch "${HOME_DIR}/.pi/.initialized"
    info "First run bootstrap complete."
fi

# ─── 5. POST-INIT: NATIVE MODULES ────────────────────────────────────────────

debug "Checking native modules..."
NEED_REBUILD=false
EXT_BASE="${HOME_DIR}/.pi/agent/git"

for ext in "${EXT_BASE}"/*/*/; do
    [[ -d "$ext/node_modules" ]] || continue
    if [[ -f "$ext/package.json" ]] && grep -q better-sqlite3 "$ext/package.json" 2>/dev/null; then
        if [[ ! -f "$ext/node_modules/better-sqlite3/build/Release/better_sqlite3.node" ]]; then
            NEED_REBUILD=true
            break
        fi
    fi
done

if [[ "$NEED_REBUILD" = "true" ]]; then
    info "Recompiling native modules (better-sqlite3) for this architecture..."
    for ext in "${EXT_BASE}"/*/*/; do
        [[ -f "$ext/package.json" ]] || continue
        if grep -q better-sqlite3 "$ext/package.json" 2>/dev/null; then
            local_name=$(basename "$(dirname "$ext")")
            info "  Rebuilding: ${local_name}..."
            (cd "$ext" && npm rebuild better-sqlite3 2>&1 | tail -2) || \
                warn "  Rebuild failed for ${local_name}"
        fi
    done
fi

# ─── 6. EXECUTE TARGET MODE ─────────────────────────────────────────────────

if [[ "$MODE" = "cli" ]]; then
    # ── CLI mode: Start Pi CLI (foreground) ─────────────────────────────
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║  LocalPibox Devstack — Pi CLI                            ║"
    echo "║  Workspace: ${WORKSPACE_DIR}                ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo ""
    echo "  pi              — Start Pi CLI session"
    echo "  exit            — Stop container"
    echo ""

    # CRITICAL FIX: cd into workspace so Pi starts in the project directory
    cd "${WORKSPACE_DIR}"
    debug "Working directory: $(pwd)"

    # Run pi in foreground
    pi "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
    EXIT_CODE=$?

    echo ""
    info "Pi session exited (code: ${EXIT_CODE}). Stopping container..."
    exit $EXIT_CODE

elif [[ "$MODE" = "web" ]]; then
    # ── Web mode: Start VSCodium server ────────────────────────────────
    export PATH="/opt/vscodium/bin:${PATH}"

    info "Starting VSCodium server on port ${ED_PORT}..."
    pkill -f "vscodium-server" 2>/dev/null || true
    sleep 1

    /opt/vscodium/bin/codium-server serve-web \
        --accept-server-license-terms \
        --host "${HOST}" \
        --port "${ED_PORT}" \
        --connection-token "${CONNECTION_TOKEN}" \
        --default-folder "${WORKSPACE_DIR}" &

    SERVER_PID=$!
    info "Server PID: ${SERVER_PID}"

    # ── Wait for readiness ─────────────────────────────────────────────
    SLEEP_INTERVAL=2
    MAX_RETRIES=30
    info "Waiting for server to be ready..."

    local_conn="http://localhost:${ED_PORT}/?tkn=${CONNECTION_TOKEN}"
    for i in $(seq 1 ${MAX_RETRIES}); do
        if curl -sf "http://localhost:${ED_PORT}/?tkn=${CONNECTION_TOKEN:-devsession}" >/dev/null 2>&1; then
            if [[ "${HOST}" = "0.0.0.0" ]]; then
                lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
                if [[ -n "$lan_ip" ]]; then
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
            echo "    exit            — Stop the server and exit"
            echo ""
            break
        fi
        if [[ "$i" -eq "$MAX_RETRIES" ]]; then
            warn "Server may not be ready yet"
        fi
        sleep ${SLEEP_INTERVAL}
    done

    # ── Run user command or start shell ────────────────────────────────
    if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
        exec "${EXTRA_ARGS[@]}"
    else
        # CRITICAL FIX: cd into workspace before starting shell
        cd "${WORKSPACE_DIR}"
        exec /bin/bash
    fi
fi
