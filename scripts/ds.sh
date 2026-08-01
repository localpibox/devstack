#!/usr/bin/env bash
# lpb — LocalPibox Devstack launcher
#
# Usage:
#   lpb [/path/to/project]              Start VSCodium at project (or home if no path)
#   lpb --stop                          Stop the container
#   lpb --remove                        Stop + remove container + state dirs
#   lpb --logs                          Stream container logs
#   lpb --update                        Pull latest image
#   lpb --config                        Show config file location
#   lpb --help                          Show usage
#
# VSCodium options (before project path):
#   --host <HOST>          Host to listen on (default: localhost)
#   --port <PORT>          Port to listen on (default: 8000)
#   --token <TOKEN>        Connection token
#   --without-token        Disable auth (trusted networks only!)
#   --data-dir <PATH>      Server data directory
#   --user-data-dir <PATH> User data directory (multiple instances)
#   --ext-dir <PATH>       Extensions root path
#   --base-path <PATH>     Web UI subpath (e.g. /ide)
#
# Config priority (highest wins):
#   1. CLI flags
#   2. Project .env (LPB_* vars)
#   3. Project override (~/.localpibox/devstack/projects/<name>)
#   4. Global config (~/.localpibox/devstack/config)
#   5. Built-in defaults

set -euo pipefail

# ─── Paths ──────────────────────────────────────────────────────────────────
CONFIG_DIR="${HOME}/.localpibox/devstack"
CONFIG_FILE="${CONFIG_DIR}/config"
PROJECTS_DIR="${CONFIG_DIR}/projects"
LAST_PROJECT_FILE="${CONFIG_DIR}/last-project"

# ─── Built-in defaults ─────────────────────────────────────────────────────
DEFAULT_PORT=8000
DEFAULT_HOST="localhost"
DEFAULT_TOKEN="devsession"
DEFAULT_IMAGE_NAME="ghcr.io/localpibox/devstack:latest"
DEFAULT_CONTAINER_NAME="localpibox"
DEFAULT_STATE_DIR="${HOME}/.localpibox/state"
DEFAULT_BROWSER_DIR="${HOME}/.localpibox/agent-browser"
DEFAULT_DATA_DIR="${CONFIG_DIR}/server-data"
DEFAULT_USER_DATA_DIR="${CONFIG_DIR}/user-data"
DEFAULT_EXT_DIR="${HOME}/.vscodium-server/extensions"
DEFAULT_BASE_PATH="/"

# ─── Resolved config ────────────────────────────────────────────────────────
LPB_IMAGE_NAME="$DEFAULT_IMAGE_NAME"
LPB_CONTAINER_NAME="$DEFAULT_CONTAINER_NAME"
LPB_PORT="$DEFAULT_PORT"
LPB_HOST="$DEFAULT_HOST"
LPB_TOKEN="$DEFAULT_TOKEN"
LPB_WITHOUT_TOKEN=false
LPB_DATA_DIR="$DEFAULT_DATA_DIR"
LPB_USER_DATA_DIR="$DEFAULT_USER_DATA_DIR"
LPB_EXT_DIR="$DEFAULT_EXT_DIR"
LPB_BASE_PATH="$DEFAULT_BASE_PATH"
LPB_STATE_DIR="$DEFAULT_STATE_DIR"
LPB_BROWSER_DIR="$DEFAULT_BROWSER_DIR"

CONTAINER_CMD=""

# ─── Helpers ────────────────────────────────────────────────────────────────

find_container_cmd() {
    command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo ""
}

ensure_container_cmd() {
    if [ -n "${CONTAINER_CMD}" ]; then
        return
    fi
    CONTAINER_CMD=$(find_container_cmd)
    if [ -z "${CONTAINER_CMD}" ]; then
        echo "ERROR: podman or docker required"
        exit 1
    fi
}

container_userns_flag() {
    ensure_container_cmd
    [[ "${CONTAINER_CMD}" == *"podman"* ]] && USERNS_FLAG="--userns keep-id" || USERNS_FLAG=""
}

pull_image() {
    ensure_container_cmd
    if ! ${CONTAINER_CMD} image inspect "${LPB_IMAGE_NAME}" >/dev/null 2>&1; then
        echo "Pulling ${LPB_IMAGE_NAME}..."
        ${CONTAINER_CMD} pull "${LPB_IMAGE_NAME}"
    fi
}

stop_existing() {
    ensure_container_cmd
    ${CONTAINER_CMD} stop "${LPB_CONTAINER_NAME}" 2>/dev/null || true
    ${CONTAINER_CMD} rm "${LPB_CONTAINER_NAME}" 2>/dev/null || true
}

# ─── Config loading (priority: lowest → highest) ────────────────────────────

load_config_file() {
    if [ -f "${CONFIG_FILE}" ]; then
        source "${CONFIG_FILE}"
    fi
}

load_project_env() {
    if [ ! -f "$1" ]; then
        return 0
    fi
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs); value=$(echo "$value" | xargs)
        case "$key" in
            LPB_*) export "$key"="$value"; export "${key#LPB_}"="$value" ;;
        esac
    done < "$1"
}

load_project_override() {
    if [ ! -f "$1" ]; then
        return 0
    fi
    source "$1"
}

write_project_override() {
    mkdir -p "${PROJECTS_DIR}"
    cat > "${PROJECTS_DIR}/$1" <<EOF
export LPB_PROJECT_PORT="${LPB_PORT}"
export LPB_PROJECT_TOKEN="${LPB_TOKEN}"
export LPB_PROJECT_HOST="${LPB_HOST}"
EOF
}

save_last_project() {
    mkdir -p "${CONFIG_DIR}"
    echo "$1" > "${LAST_PROJECT_FILE}"
}

# ─── Apply overrides ────────────────────────────────────────────────────────

apply_overrides() {
    # Config file (priority 4)
    load_config_file
    [ -n "${LPB_IMAGE_NAME:-}" ]       && LPB_IMAGE_NAME="${LPB_IMAGE_NAME}"
    [ -n "${LPB_CONTAINER_NAME:-}" ]   && LPB_CONTAINER_NAME="${LPB_CONTAINER_NAME}"
    [ -n "${LPB_PORT:-}" ]             && LPB_PORT="${LPB_PORT}"
    [ -n "${LPB_EDITOR_HOST:-}" ]      && LPB_HOST="${LPB_EDITOR_HOST}"
    [ -n "${LPB_CONNECTION_TOKEN:-}" ] && LPB_TOKEN="${LPB_CONNECTION_TOKEN}"
    [ -n "${LPB_STATE_DIR:-}" ]        && LPB_STATE_DIR="${LPB_STATE_DIR}"
    [ -n "${LPB_BROWSER_DIR:-}" ]      && LPB_BROWSER_DIR="${LPB_BROWSER_DIR}"
    [ -n "${LPB_DATA_DIR:-}" ]         && LPB_DATA_DIR="${LPB_DATA_DIR}"
    [ -n "${LPB_USER_DATA_DIR:-}" ]    && LPB_USER_DATA_DIR="${LPB_USER_DATA_DIR}"
    [ -n "${LPB_EXT_DIR:-}" ]          && LPB_EXT_DIR="${LPB_EXT_DIR}"
    [ -n "${LPB_BASE_PATH:-}" ]        && LPB_BASE_PATH="${LPB_BASE_PATH}"

    # Project .env (priority 2)
    if [ -n "${PROJECT_DIR:-}" ] && [ -f "${PROJECT_DIR}/.env" ]; then
        load_project_env "${PROJECT_DIR}/.env"
        [ -n "${LPB_PORT:-}" ]             && LPB_PORT="${LPB_PORT}"
        [ -n "${LPB_CONNECTION_TOKEN:-}" ] && LPB_TOKEN="${LPB_CONNECTION_TOKEN}"
        [ -n "${LPB_EDITOR_HOST:-}" ]      && LPB_HOST="${LPB_EDITOR_HOST}"
    fi

    # Project override (priority 3)
    if [ -n "${PROJECT_NAME:-}" ]; then
        load_project_override "${PROJECTS_DIR}/${PROJECT_NAME}"
        [ -n "${LPB_PROJECT_PORT:-}" ]     && LPB_PORT="${LPB_PROJECT_PORT}"
        [ -n "${LPB_PROJECT_TOKEN:-}" ]    && LPB_TOKEN="${LPB_PROJECT_TOKEN}"
        [ -n "${LPB_PROJECT_HOST:-}" ]     && LPB_HOST="${LPB_PROJECT_HOST}"
    fi
}

# ─── CLI parsing ────────────────────────────────────────────────────────────

parse_cli() {
    local positional=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --host)          LPB_HOST="$2"; shift 2 ;;
            --port)          LPB_PORT="$2"; shift 2 ;;
            --token)         LPB_TOKEN="$2"; shift 2 ;;
            --without-token) LPB_WITHOUT_TOKEN=true; shift ;;
            --data-dir)      LPB_DATA_DIR="$2"; shift 2 ;;
            --user-data-dir) LPB_USER_DATA_DIR="$2"; shift 2 ;;
            --ext-dir)       LPB_EXT_DIR="$2"; shift 2 ;;
            --base-path)     LPB_BASE_PATH="$2"; shift 2 ;;
            --stop|-s)       COMMAND="stop"; shift ;;
            --remove|-r)     COMMAND="remove"; shift ;;
            --logs|-l)       COMMAND="logs"; shift ;;
            --update|-u)     COMMAND="update"; shift ;;
            --config|-c)     COMMAND="config"; shift ;;
            --help|-h)       COMMAND="help"; shift ;;
            --)              shift; positional+=("$"); break ;;
            --*)             echo "Unknown option: $1"; exit 1 ;;
            *)               positional+=("$1"); shift ;;
        esac
    done
    # Handle --help when it was passed as a positional arg (after a path)
    for p in "${positional[@]+${positional[@]}}"; do
        case "$p" in
            --help|-h|help) COMMAND="help" ;;
        esac
    done
    PROJECT_DIR="${positional[0]:-}"
    OPEN_HOME="${positional[1]:-false}"
}

# ─── Commands ───────────────────────────────────────────────────────────────

cmd_help() {
    cat <<EOF
lpb — LocalPibox Devstack launcher

Usage:
  lpb [/path/to/project]           Start VSCodium at project (or home if no path)
  lpb --stop                       Stop the container
  lpb --remove                     Stop + remove container + state dirs
  lpb --logs                       Stream container logs
  lpb --update                     Pull latest image
  lpb --config                     Show config file location
  lpb --help                       Show this help

VSCodium options (before project path):
  --host <HOST>          Host to listen on (default: localhost)
  --port <PORT>          Port to listen on (default: 8000)
  --token <TOKEN>        Connection token
  --without-token        Disable auth (trusted networks only!)
  --data-dir <PATH>      Server data directory
  --user-data-dir <PATH> User data directory (multiple instances)
  --ext-dir <PATH>       Extensions root path
  --base-path <PATH>     Web UI subpath (e.g. /ide)

Config files:
  Global:  ~/.localpibox/devstack/config
  Project: ~/.localpibox/devstack/projects/<project-name>

Examples:
  lpb                                Open VSCodium at ~ (user picks project)
  lpb /home/user/myproject           Open VSCodium at project
  lpb /home/user/myproject --port 8080   Custom port
  lpb --host 0.0.0.0 --token mysecret  LAN access with custom token
  lpb --without-token                 No auth (localhost only!)
EOF
    exit 0
}

cmd_stop() {
    ensure_container_cmd
    ${CONTAINER_CMD} stop -t 30 "${LPB_CONTAINER_NAME}" 2>/dev/null && echo "Stopped." || echo "Not running."
}

cmd_remove() {
    ensure_container_cmd
    ${CONTAINER_CMD} stop -t 30 "${LPB_CONTAINER_NAME}" 2>/dev/null || true
    ${CONTAINER_CMD} rm -f "${LPB_CONTAINER_NAME}" 2>/dev/null || true
    rm -rf "${LPB_STATE_DIR}" "${LPB_BROWSER_DIR}"
    echo "Removed devstack."
}

cmd_logs() {
    ensure_container_cmd
    ${CONTAINER_CMD} logs -f "${LPB_CONTAINER_NAME}" 2>/dev/null || echo "Container not running."
}

cmd_update() {
    ensure_container_cmd
    echo "Pulling ${LPB_IMAGE_NAME}..."
    ${CONTAINER_CMD} pull "${LPB_IMAGE_NAME}"
}

cmd_config() {
    echo "Config file: ${CONFIG_FILE}"
    echo "Projects:    ${PROJECTS_DIR}"
    echo "State dir:   ${LPB_STATE_DIR}"
    echo "Browser dir: ${LPB_BROWSER_DIR}"
}

# ─── Main run ───────────────────────────────────────────────────────────────

cmd_run() {
    ensure_container_cmd
    container_userns_flag

    # Determine project dir
    local project_dir="${PROJECT_DIR}"
    local open_home="${OPEN_HOME:-false}"

    if [ -z "${project_dir}" ]; then
        # Try last used project
        if [ -f "${LAST_PROJECT_FILE}" ]; then
            project_dir=$(cat "${LAST_PROJECT_FILE}")
            if [ ! -d "${project_dir}" ]; then
                project_dir=""
            fi
        fi
    fi

    if [ -z "${project_dir}" ]; then
        open_home=true
        project_dir="${HOME}"
    fi

    [ ! -d "${project_dir}" ] && { echo "Error: directory not found: ${project_dir}"; exit 1; }

    mkdir -p "${LPB_STATE_DIR}" "${LPB_BROWSER_DIR}"

    PROJECT_NAME=$(basename "${project_dir}")
    MOUNT_PATH="/home/dev/workspace/${PROJECT_NAME}"

    # Show summary
    echo "Devstack: ${PROJECT_NAME}"
    echo "  Image:    ${LPB_IMAGE_NAME}"
    echo "  Project:  ${project_dir} → ${MOUNT_PATH}"
    echo "  Editor:   http://${LPB_HOST}:${LPB_PORT}"
    if [ "${LPB_WITHOUT_TOKEN}" = true ]; then
        echo "  Auth:     none (⚠ unsecured)"
    else
        echo "  Token:    ${LPB_TOKEN:0:8}..."
    fi
    echo ""

    [ "${open_home}" = true ] && echo "Starting VSCodium — select a project in the welcome screen."

    # Build environment args
    local ENV_ARGS=()
    ENV_ARGS+=(
        -e LPB_ED_PORT="${LPB_PORT}"
        -e LPB_EDITOR_HOST="${LPB_HOST}"
        -e LPB_DEVCONTAINER_WORKSPACE_DIR="${MOUNT_PATH}"
        -e LPB_CONNECTION_TOKEN="${LPB_TOKEN}"
        -e LPB_STATE_DIR="/home/dev/.pi"
    )

    # Build volume mounts
    local VOLUMES=()
    VOLUMES+=(
        -v "${project_dir}:${MOUNT_PATH}:Z"
        -v "${LPB_STATE_DIR}:/home/dev/.pi:Z"
        -v "${LPB_BROWSER_DIR}:/home/dev/.agent-browser:Z"
    )

    # Stop existing if reconnecting
    if [ "${open_home}" = true ] && [ "${PROJECT_DIR:-}" != "" ]; then
        stop_existing
    fi

    # Pull image
    pull_image

    # Start container
    echo "Running..."
    ${CONTAINER_CMD} run -d \
        --name "${LPB_CONTAINER_NAME}" \
        --network host \
        ${USERNS_FLAG} \
        ${ENV_ARGS[@]} \
        ${VOLUMES[@]} \
        "${LPB_IMAGE_NAME}"

    # Health check
    local HEALTH_URL
    if [ "${LPB_WITHOUT_TOKEN}" = true ]; then
        HEALTH_URL="http://${LPB_HOST}:${LPB_PORT}/"
    else
        HEALTH_URL="http://${LPB_HOST}:${LPB_PORT}/?tkn=${LPB_TOKEN}"
    fi

    echo "Waiting for editor..."
    for i in $(seq 1 60); do
        if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
            echo ""
            echo "✓ Devstack ready at ${HEALTH_URL}"
            echo ""
            echo "  lpb --logs     — View logs"
            echo "  lpb --stop     — Stop"
            echo "  lpb --remove   — Remove everything"
            echo "  lpb            — Reconnect to last project"
            exit 0
        fi
        sleep 1
    done
    echo "⚠ Container running but editor may not be ready. Check: lpb --logs"
}

# ─── Entry point ────────────────────────────────────────────────────────────

# Parse CLI first (commands are handled here, not in case)
parse_cli "$@"

# 1. Load defaults from config file
load_config_file

# 2. Apply overrides in priority order
apply_overrides

# 3. Execute command
COMMAND="${COMMAND:-run}"
case "${COMMAND}" in
    stop|stop)     cmd_stop ;;
    remove|remove) cmd_remove ;;
    logs|logs)     cmd_logs ;;
    update|update) cmd_update ;;
    config|config) cmd_config ;;
    help|help)     cmd_help ;;
    *)             cmd_run ;;
esac
