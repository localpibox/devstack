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

# ─── Shared helpers (env parse, migration, account unlock) ──────────────────
source /opt/pi-support/_lib.sh

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
    while IFS= read -r _line; do
        key="${_line%%=*}"
        value="${_line#*=}"
        export "$key"="$value"
        # Strip LPB_ prefix to create unprefixed alias
        stripped="${key#LPB_}"
        if [[ "$stripped" != "$key" && -n "$value" && -z "${!stripped+x}" ]]; then
            export "$stripped"="$value"
        fi
    done < <(parse_env_file "${_stack_conf}")
fi

# Stack identity (image names, forks, versions) — baked at build time.
# Provides LPB_CONFIG_FORK / LPB_CONFIG_REF defaults for the clone below.
# NOTE: Runtime env vars (-e from lpb.py) take precedence over baked values.
_stack_env="/opt/devstack/lpb.stack.env"
if [[ -f "${_stack_env}" ]]; then
    debug "Loading build identity from ${_stack_env}"
    while IFS= read -r _line; do
        # Skip lines where the env var is already set (runtime override)
        _key="${_line%%=*}"
        if [[ -n "${!_key+x}" ]]; then
            continue
        fi
        export "$_line"
    done < <(parse_env_file "${_stack_env}")
fi

# --- 0b. INLINE FALLBACK DEFAULTS (if lpb.conf.env is missing) ---
export HOME_DIR="/home/lpb"
export PATH="/home/lpb/.npm-global/bin:/home/lpb/.local/bin:${PATH}"

# -- Date/time — always available to the agent for context awareness --
export PI_DATE="$(date '+%Y-%m-%d')"
export PI_TIME="$(date '+%H:%M:%S %Z')"

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
export LPB_CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN:-${CONNECTION_TOKEN:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')}}"

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


# -- Browser config (preserve lpb.py defaults, allow shell override) --
export LPB_AGENT_BROWSER_ARGS="${LPB_AGENT_BROWSER_ARGS:-}"
export LPB_AGENT_BROWSER_MAX_OUTPUT="${LPB_AGENT_BROWSER_MAX_OUTPUT:-4000}"
export LPB_AGENT_BROWSER_CONTENT_BOUNDARIES="${LPB_AGENT_BROWSER_CONTENT_BOUNDARIES:-true}"
export LPB_AGENT_BROWSER_CONFIRM_ACTIONS="${LPB_AGENT_BROWSER_CONFIRM_ACTIONS:-delete,download,cookie_delete,file_access}"
export LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS="${LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS:-300000}"
export LPB_AGENT_BROWSER_SESSION="${LPB_AGENT_BROWSER_SESSION:-${PI_WORKTREE_ID:-}}"

# ── API keys & other LPB_ → bare-name bridges ────────────────────────────────
# Define bare-name aliases here. The _bridge() loop applies the generic logic:
#   LPB_FOO → FOO (only if FOO not already set by shell env).
# Fallback chain: shell env > LPB_ (from .env/conf) > hardcoded.
#
# NOTE: GITHUB_TOKEN is excluded — it has a special fallback chain:
#   shell env > LPB_ > `gh auth token` (CLI auth) > empty.
# That special case runs below, after _bridge.
_bridge() {
    local _name lpb_name
    # Build LPB_ prefix with fallback to bare name (shell env wins)
    for _name in "${BARE_NAMES[@]}"; do
        lpb_name="LPB_${_name}"
        export "$lpb_name="${!lpb_name:-${!_name:-}}""
    done
    # Promote LPB_ → bare (only if bare not already in shell env)
    for _name in "${BARE_NAMES[@]}"; do
        lpb_name="LPB_${_name}"
        if [[ -z "${!_name+x}" ]]; then
            export "$_name="${!lpb_name:-}""
        fi
    done
}

# Define the full list of LPB_ → bare-name pairs.
BARE_NAMES=(
    EXA_API_KEY
    CONTEXT7_API_KEY
    LEMONADE_BASE_URL
    OPENROUTER_BASE_URL
    ED_PORT
    HOST
    CONNECTION_TOKEN
    DEVCONTAINER_WORKSPACE_DIR
    MAX_TOKENS_CONTEXT_RATIO
)

# Apply bridge after lpb.conf.env defaults (step 0).
_bridge

# ── GitHub Token (from gh auth token or shell env) ──
# lpb.conf.env may set LPB_GITHUB_TOKEN to a literal string; start.sh
# resolves the actual token by trying: shell env > LPB_GITHUB_TOKEN (literal) > gh auth token.
export GITHUB_TOKEN="${GITHUB_TOKEN:-${LPB_GITHUB_TOKEN:-$(gh auth token 2>/dev/null || true)}}"
# Canonical env var name the github-mcp-server binary reads for stdio auth.
# mcp.json resolves ${GITHUB_PERSONAL_ACCESS_TOKEN} from this export.
export GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_TOKEN}"
export LPB_GITHUB_TOKEN="${GITHUB_TOKEN}"

# ── GitHub MCP Server toolsets (see mcp.json for transport config) ──
export GITHUB_TOOLSETS="${GITHUB_TOOLSETS:-${LPB_GITHUB_TOOLSETS:-all}}"

# ── Persistence flags ──
export LPB_PERSIST_GH_CONFIG="${LPB_PERSIST_GH_CONFIG:-true}"

debug "LEMONADE_BASE_URL=$LEMONADE_BASE_URL"
debug "WORKSPACE_DIR=$WORKSPACE_DIR"
debug "ED_PORT=$ED_PORT"
debug "EDITOR_HOST=$HOST"
debug "MAX_TOKENS_CONTEXT_RATIO=$MAX_TOKENS_CONTEXT_RATIO"

# ─── 2. RESOLVE PROJECT DIRECTORY & LOAD .ENV ──────────────────────────────
# The project is a subdirectory of the workspace (e.g. "/home/lpb/workspace/<project>")
# and does not need to contain a .env. lpb.py is the authoritative source: it mounts
# the project there and sets LPB_DEVCONTAINER_WORKSPACE_DIR to the mount path.
# Fall back to the current working directory when lpb.py didn't set it (manual start).

PROJECT_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-$(pwd)}"
export PROJECT_DIR
debug "PROJECT_DIR=$PROJECT_DIR"

# Load variables from the project's .env (LPB_* prefix only) if present — it is optional.
ENV_FILE=""
_candidates=(
    "${PROJECT_DIR}/.env"
    "${WORKSPACE_DIR}/.env"
    "${WORKSPACE_DIR}/devstack/.env"
)
for _cand in "${_candidates[@]}"; do
    if [[ -n "$_cand" && -f "$_cand" ]]; then
        ENV_FILE="$_cand"
        debug "Found .env at ${ENV_FILE}"
        break
    fi
done

if [[ -n "$ENV_FILE" ]]; then
    info "Loading environment from ${ENV_FILE}"
    while IFS= read -r _line; do
        case "$_line" in LPB_*=*) ;; *) continue ;; esac
        key="${_line%%=*}"
        value="${_line#*=}"
        export "$key"="$value"
        # Strip LPB_ prefix — only if value is non-empty and bare name isn't set
        stripped="${key#LPB_}"
        if [[ -n "$value" && -z "${!stripped+x}" ]]; then
            export "$stripped"="$value"
        fi
    done < <(parse_env_file "$ENV_FILE")
    # Re-read key values after .env load
    WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-$WORKSPACE_DIR}"
    export WORKSPACE_DIR

    # Re-apply LPB_ → bare-name bridge now that .env may have added new LPB_* values.
    _bridge
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

# ─── 4a. CONFIG REPO — CLONE/FETCH INTO ~/.pi/agent/ (BEFORE FIRST-RUN) ────
# The config repo (localpibox/config) IS the runtime agent config directory
# (~/.pi/agent/). Pi reads the repo root directly via PI_CODING_AGENT_DIR.
# The agent dir is ~/.pi/agent/ (upstream pi default) — NOT ~/.pi/ root —
# because pi and its extensions hardcode that path: getAgentDir() defaults to
# ~/.pi/agent/, package-manager keeps git/npm under <agentDir>/, and the
# lemonade plugin reads/writes ~/.pi/agent/auth.json and models-store.json.
# Done BEFORE first-run mkdirs so ~/.pi/agent/ is empty when we clone into it.
# Runs every boot: clones on first run, non-destructive fetch afterwards.
AGENT_PI_ROOT="${HOME_DIR}/.pi"
AGENT_DIR="${AGENT_PI_ROOT}/agent"
# Config preset repo — baked into the image from lpb.stack.env (Dockerfile
# ENV LPB_CONFIG_REMOTE / LPB_CONFIG_REF). Shell env can still override.
CONFIG_REMOTE="${LPB_CONFIG_REMOTE:-${LPB_CONFIG_FORK:-https://github.com/localpibox/config.git}}"
CONFIG_REF="${LPB_CONFIG_REF:-main}"

export PI_CODING_AGENT_DIR="${AGENT_DIR}"

# ── Migrate legacy ~/.pi root layout → ~/.pi/agent/ (one-time) ──────────
# Earlier versions used ~/.pi/ root as the agent dir: the config repo (.git)
# plus all runtime state (auth.json, models-store.json, sessions/, git/, npm/)
# lived directly in ~/.pi. That broke pi's hardcoded ~/.pi/agent/* paths.
# One-time relocation: move everything (repo + untracked runtime) into
# ~/.pi/agent/, leaving only infra markers (.initialized, ssh-host-keys) at
# the root. No-op on fresh volumes or already-reshaped ones.
_migrate_legacy_layout "${AGENT_PI_ROOT}" "${AGENT_DIR}" info

if [[ ! -d "${AGENT_DIR}/.git" ]]; then
    if [[ -d "${AGENT_DIR}" && -n "$(ls -A "${AGENT_DIR}" 2>/dev/null)" ]]; then
        # ~/.pi already exists and is non-empty but not a git repo — e.g. stale
        # pre-refactor state, or a fresh container booting over a persisted
        # ~/.pi volume. `git clone` refuses a non-empty target, so initialize
        # the repo in place instead. Existing files are left untouched
        # (gitignored by the config repo) so nothing is lost.
        info "Config area not empty — initializing config repo in place..."
        if git -C "${AGENT_DIR}" init -q \
            && git -C "${AGENT_DIR}" remote add origin "${CONFIG_REMOTE}" 2>/dev/null \
            && git -C "${AGENT_DIR}" fetch --depth=1 origin "${CONFIG_REF}"; then
            # Reset to the fetched ref: tracked files land at the repo root,
            # untracked runtime state stays as-is. No force (won't clobber a
            # conflicting local i.e. settings file).
            git -C "${AGENT_DIR}" reset -q --hard "origin/${CONFIG_REF}" 2>/dev/null || true
            info "Config repo initialized."
        else
            warn "Config repo initialization failed — Pi will use defaults."
        fi
    else
        info "Cloning config repo from ${CONFIG_REMOTE}..."
        if git clone --depth=1 --branch "${CONFIG_REF}" "${CONFIG_REMOTE}" "${AGENT_DIR}"; then
            info "Config repo cloned."
        else
            warn "Config clone failed — Pi will use defaults."
        fi
    fi
else
    # Non-destructive fetch only — local customizations are never wiped.
    # Use 'lpb-config update/reset/merge' for actual updates.
    git -C "${AGENT_DIR}" fetch origin "${CONFIG_REF}" 2>/dev/null || true
    debug "Config repo fetched (manual update via lpb-config)."
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

    mkdir -p "${AGENT_DIR}/git" \
             "${AGENT_DIR}/npm" \
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

    # Pre-create .npmrc so npm reads allow-scripts from parent dir
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > "${AGENT_DIR}/git/.npmrc" 2>/dev/null || true
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > "${HOME_DIR}/.npmrc" 2>/dev/null || true

    # ── Config repo: clone/fetch into ~/.pi/agent/ (runs every boot — see §4a)
    touch "${HOME_DIR}/.pi/.initialized"

    # ── Unlock the lpb account (locked by default; unlock so SSH key auth works) ─
    _unlock_account "$(stat -c %U "${HOME_DIR}" 2>/dev/null || echo "lpb")" "sudo -n" info

    info "First run bootstrap complete."
fi

# ─── 4b. ENSURE HOME MOUNT PARENTS ARE WRITABLE (EVERY BOOT) ────────────────
# The container runtime recreates host-volume bind-mount parents (e.g.
# /home/lpb/.config for the gh-config mount) as root on boot, so a directory
# that was lpb-owned in the image can silently become root-owned again.
# start.sh only chowned these on first run, which left them broken on later
# boots. Tools that write under ~/.config at runtime then fail — most notably
# Chrome/agent-browser, whose crashpad handler cannot create
# ~/.config/google-chrome/ and dies with "chrome_crashpad_handler:
# --database is required" (Chrome exits 133 / SIGTRAP). Re-assert ownership
# every boot regardless of first-run state.
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    for _d in "${HOME_DIR}/.config" "${HOME_DIR}/.local"; do
        if [[ -e "$_d" && "$(stat -c %u "$_d" 2>/dev/null)" != "$(id -u)" ]]; then
            info "Fixing ownership of $_d (runtime-created mount parent)..."
            sudo -n chown "$(id -u):$(id -g)" "$_d" 2>/dev/null || true
        fi
    done
fi

# ─── 4c. PERSIST DEVSTACK ENV FOR ALL SHELLS (--shell / --ssh) ─────────────
# start.sh loads .env and computes the LPB_* vars + bare-name aliases, but those
# only exist in this process. Interactive --shell bash inherits them (via exec),
# but --ssh login shells and `podman exec bash` reattachments start fresh and
# would miss them. Persist the resolved set to ~/.devstack-env and source it from
# .bashrc and .profile so every shell (SSH, exec, interactive) gets the
# preconfigured env vars (e.g. EXA_API_KEY).
persist_devstack_env() {
    local env_file="${HOME_DIR}/.devstack-env"
    : > "${env_file}"
    # Dump all LPB_*/PI_* vars plus the aliased bare names (non-empty only).
    while IFS= read -r name; do
        [[ -n "$name" ]] || continue
        local val="${!name}"
        [[ -n "$val" ]] || continue
        printf -v q '%q' "$val"
        printf 'export %s=%s\n' "$name" "$q" >> "${env_file}"
    done < <({
        env | cut -d= -f1 | grep -E '^(LPB_|PI_)'
        for n in "${BARE_NAMES[@]}"; do [[ -n "${!n:-}" ]] && echo "$n"; done
        # GitHub token is resolved by special case (gh auth token) — must persist for interactive shells
        [[ -n "${GITHUB_TOKEN:-}" ]] && echo "GITHUB_TOKEN"
    })
    chmod 600 "${env_file}" 2>/dev/null || true
    # Source it from .bashrc and .profile, idempotently.
    local src_marker='# LocalPibox devstack environment (managed)'
    local src_line='[ -f "${HOME}/.devstack-env" ] && . "${HOME}/.devstack-env"'
    local rc
    for rc in "${HOME_DIR}/.bashrc" "${HOME_DIR}/.profile"; do
        [[ -f "$rc" ]] || continue
        if ! grep -qF "$src_marker" "$rc" 2>/dev/null; then
            printf '\n%s\n%s\n' "$src_marker" "$src_line" >> "$rc"
        fi
    done
}
persist_devstack_env

# ─── 5. POST-INIT: NATIVE MODULES ────────────────────────────────────────────

debug "Checking native modules..."
NEED_REBUILD=false
EXT_BASE="${AGENT_DIR}/git"

# Look for any better-sqlite3 that's missing its bindings
while IFS= read -r pkg_json; do
    [[ -f "$pkg_json" ]] || continue
    ext_dir=$(dirname "$pkg_json")
    node_modules="${ext_dir}/node_modules/better-sqlite3"
    # Only process extensions that have better-sqlite3 in their package.json
    grep -q 'better-sqlite3' "$pkg_json" 2>/dev/null || continue
    if [[ -f "$node_modules/package.json" ]]; then
        # Check all possible paths where the .node binding could be
        binding_found=false
        for path in \
            "${node_modules}/build/Release/better_sqlite3.node" \
            "${node_modules}/build/Debug/better_sqlite3.node" \
            "${node_modules}/build/better_sqlite3.node" \
            "${node_modules}/out/Debug/better_sqlite3.node" \
            "${node_modules}/out/Release/better_sqlite3.node" \
            "${node_modules}/prebuilds/linux-x64/better_sqlite3.node" \
            "${node_modules}/prebuilds/linux-arm64/better_sqlite3.node"; do
            [[ -f "$path" ]] && binding_found=true && break
        done
        if [[ "$binding_found" = "false" ]]; then
            NEED_REBUILD=true
            break
        fi
    fi
done < <(find "${EXT_BASE}" -maxdepth 3 -name "package.json" -not -path "*node_modules*" 2>/dev/null)

if [[ "$NEED_REBUILD" = "true" ]]; then
    info "Recompiling native modules (better-sqlite3) for this architecture..."
    while IFS= read -r pkg_json; do
        [[ -f "$pkg_json" ]] || continue
        ext_dir=$(dirname "$pkg_json")
        node_modules="${ext_dir}/node_modules/better-sqlite3"
        grep -q 'better-sqlite3' "$pkg_json" 2>/dev/null || continue
        if [[ -d "$node_modules" ]]; then
            binding_found=false
            for path in \
                "${node_modules}/build/Release/better_sqlite3.node" \
                "${node_modules}/build/Debug/better_sqlite3.node" \
                "${node_modules}/build/better_sqlite3.node" \
                "${node_modules}/out/Debug/better_sqlite3.node" \
                "${node_modules}/out/Release/better_sqlite3.node" \
                "${node_modules}/prebuilds/linux-x64/better_sqlite3.node"; do
                [[ -f "$path" ]] && binding_found=true && break
            done
            if [[ "$binding_found" = "false" ]]; then
                local_name=$(echo "$ext_dir" | sed "s|.*/\.pi/agent/git/||")
                info "  Rebuilding: ${local_name}..."
                (cd "$ext_dir" && PATH="/home/lpb/.npm-global/bin:${PATH}" npm rebuild better-sqlite3 --loglevel=error 2>&1 | tail -3) || \
                    warn "  npm rebuild failed for ${local_name}, trying node-gyp..."
                # If npm rebuild failed, try node-gyp
                (cd "${node_modules}" && PATH="/home/lpb/.npm-global/bin:${PATH}" npx -y node-gyp rebuild 2>&1 | tail -3) || \
                    warn "  Rebuild failed for ${local_name} — manual fix required"
            fi
        fi
    done < <(find "${EXT_BASE}" -maxdepth 3 -name "package.json" -not -path "*node_modules*" 2>/dev/null)
    info "Native modules rebuild complete."
fi

# ─── 6. EXECUTE TARGET MODE ─────────────────────────────────────────────────

if [[ "$MODE" = "shell" ]]; then
    # ── Shell mode: serve workspace + optional interactive shell, stay alive ──
    # Used by "lpb --shell" when no container exists (bare shell, no Pi session)
    # and by "lpb --ssh" (sshd stays running; user logs in remotely).
    cd "${PROJECT_DIR}" 2>/dev/null || true
    debug "Shell mode; working directory: $(pwd)"

    # If an SSH pubkey was provided, run sshd so the user can log in.
    if [[ -n "${LPB_SSH_PUBKEY:-}" ]]; then
        export PATH="/usr/sbin:/usr/bin:${PATH}"
        if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
            SUDO="sudo -n"
        else
            SUDO=""
        fi
        if command -v sshd >/dev/null 2>&1; then
            mkdir -p "${HOME_DIR}/.ssh"
            chmod 700 "${HOME_DIR}/.ssh"
            echo "${LPB_SSH_PUBKEY}" > "${HOME_DIR}/.ssh/authorized_keys"
            chmod 600 "${HOME_DIR}/.ssh/authorized_keys"
            chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.ssh" 2>/dev/null || true
            # Persistent host keys — avoid "remote host identification changed"
            # when the container is recreated. Stored under the persisted ~/.pi
            # state dir (lpb-writable) so the same host identity is reused.
            HOSTKEY_DIR="${HOME_DIR}/.pi/ssh-host-keys"
            mkdir -p "${HOSTKEY_DIR}"
            chmod 700 "${HOSTKEY_DIR}"
            if [[ ! -f "${HOSTKEY_DIR}/ssh_host_ed25519_key" ]]; then
                ssh-keygen -q -t ed25519 -f "${HOSTKEY_DIR}/ssh_host_ed25519_key" -N '' -C '' >/dev/null 2>&1 || true
            fi
            # sshd as a non-root user runs with privilege separation in /run/sshd;
            # that dir must exist and be owned by lpb so sshd can use it.
            mkdir -p /run/sshd 2>/dev/null
            chown -R "$(id -u):$(id -g)" /run/sshd 2>/dev/null || true
            chmod 755 /run/sshd 2>/dev/null || true
            # Per-user sshd_config (lpb-writable) — avoids /etc/ssh permissions
            SSHD_CONFIG="${HOME_DIR}/.ssh/sshd_config"
            cat > "${SSHD_CONFIG}" <<EOF
Port ${LPB_SSH_PORT:-2222}
HostKey ${HOSTKEY_DIR}/ssh_host_ed25519_key
PidFile ${HOME_DIR}/.ssh/sshd.pid
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin no
AuthorizedKeysFile .ssh/authorized_keys
Subsystem sftp internal-sftp
EOF
            chmod 600 "${SSHD_CONFIG}"

            # Unlock the lpb account for SSH key auth
            _unlock_account "$(stat -c %U "${HOME_DIR}" 2>/dev/null || echo "lpb")" "${SUDO}" info

            info "Starting sshd on port ${LPB_SSH_PORT:-2222}..."
            # Run sshd in the foreground in the background; it requires root for
            # privilege separation, so use sudo when available.
            if [[ -n "${SUDO}" ]]; then
                ${SUDO} /usr/sbin/sshd -f "${SSHD_CONFIG}" 2>&1 | tail -3
            else
                /usr/sbin/sshd -f "${SSHD_CONFIG}" 2>&1 | tail -3
            fi
        else
            warn "sshd not available; SSH disabled (run with no pubkey for a bare shell)."
        fi
    fi

    info "Devstack shell ready. Workspace: ${PROJECT_DIR}"
    if [[ -t 0 ]]; then
        info "Type 'exit' to stop the container."
        exec bash -l
    else
        # Non-interactive / server context: keep the container alive
        # (canonical devcontainer pattern: CMD ["sleep", "infinity"])
        info "Container alive; use 'lpb --stop' to shut it down."
        sleep infinity
    fi

elif [[ "$MODE" = "cli" ]]; then
    # ── CLI mode: Start Pi CLI (foreground) ─────────────────────────────
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║  LocalPibox Devstack — Pi CLI                            ║"
    echo "║  Workspace: ${PROJECT_DIR}                ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo ""
    echo "  pi              — Start Pi CLI session"
    echo "  exit            — Stop container"
    echo ""

    # CRITICAL FIX: cd into project directory so Pi starts in the project
    cd "${PROJECT_DIR}"
    debug "Working directory: $(pwd)"

    # Run pi in foreground
    pi "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
    EXIT_CODE=$?

    echo ""
    info "Pi session exited (code: ${EXIT_CODE}). Stopping container..."
    exit $EXIT_CODE

elif [[ "$MODE" = "web" ]]; then
    # ── Web mode: Start VSCodium server (foregound) ────────────────────
    export PATH="/opt/vscodium/bin:${PATH}"

    # Verify the server binary exists
    if [[ ! -x "/opt/vscodium/bin/codium-server" ]]; then
        warn "ERROR: codium-server binary not found at /opt/vscodium/bin/codium-server"
        ls -la /opt/vscodium/bin/ 2>/dev/null || true
        exit 1
    fi

    info "Starting VSCodium server on port ${ED_PORT}..."

    # Start server in FOREGROUND with exec.
    # This replaces the bash process with the server, so ALL server output
    # (stdout + stderr) goes directly to the container's log buffer.
    # When the user runs `lpb --shell`, it uses `podman exec` to attach
    # a new bash process without stopping the server (PID 1).
    exec /opt/vscodium/bin/codium-server serve-web \
        --accept-server-license-terms \
        --host "${HOST}" \
        --port "${ED_PORT}" \
        --connection-token "${CONNECTION_TOKEN}" \
        --default-folder "${PROJECT_DIR}"
fi
