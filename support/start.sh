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
        # Strip LPB_ prefix to create unprefixed alias — ONLY if value is non-empty.
        # Empty LPB_ values must NOT block .env or shell overrides of the bare name.
        stripped="${key#LPB_}"
        if [[ "$stripped" != "$key" && -n "$value" && -z "${!stripped+x}" ]]; then
            export "$stripped"="$value"
        fi
    done < "${_stack_conf}"
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


# ── Browser config ──
export LPB_AGENT_BROWSER_ARGS="${LPB_AGENT_BROWSER_ARGS:-}"
export LPB_AGENT_BROWSER_MAX_OUTPUT="${LPB_AGENT_BROWSER_MAX_OUTPUT:-4000}"
export LPB_AGENT_BROWSER_CONTENT_BOUNDARIES="${LPB_AGENT_BROWSER_CONTENT_BOUNDARIES:-true}"
export LPB_AGENT_BROWSER_CONFIRM_ACTIONS="${LPB_AGENT_BROWSER_CONFIRM_ACTIONS:-delete,download,cookie_delete,file_access}"
export LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS="${LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS:-300000}"
export LPB_AGENT_BROWSER_SESSION="${LPB_AGENT_BROWSER_SESSION:-${PI_WORKTREE_ID:-}}"

# ── Exa API key ──
export LPB_EXA_API_KEY="${LPB_EXA_API_KEY:-${EXA_API_KEY:-}}"

# ── Persistence flags ──
export LPB_PERSIST_GH_CONFIG="${LPB_PERSIST_GH_CONFIG:-true}"

debug "LEMONADE_BASE_URL=$LEMONADE_BASE_URL"
debug "WORKSPACE_DIR=$WORKSPACE_DIR"
debug "ED_PORT=$ED_PORT"
debug "EDITOR_HOST=$HOST"
debug "MAX_TOKENS_CONTEXT_RATIO=$MAX_TOKENS_CONTEXT_RATIO"

# ─── 2. LOAD .ENV FROM PROJECT WORKSPACE ─────────────────────────────────────
# Variables from the project's .env file (LPB_* prefix only) override defaults.
# Search multiple candidate locations so the .env is found whether the project
# is mounted at the workspace root OR as a project subdir (e.g. devstack repo
# mounted at ${WORKSPACE_DIR}/devstack), and regardless of the start.sh cwd.

ENV_FILE=""
_candidates=(
    "${WORKSPACE_DIR}/.env"
    "${WORKSPACE_DIR}/devstack/.env"
    "$(pwd)/.env"
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
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        [[ "$line" != *=* ]] && continue
        key=$(echo "$line" | cut -d= -f1 | xargs 2>/dev/null || echo "$line" | cut -d= -f1)
        value=$(echo "$line" | cut -d= -f2- | xargs 2>/dev/null || echo "$line" | cut -d= -f2-)
        case "$key" in
            LPB_*)
                export "$key"="$value"
                # Strip LPB_ prefix to create unprefixed alias — only if value is non-empty
                # AND the bare name wasn't already set (shell/env always wins over .env).
                stripped="${key#LPB_}"
                if [[ -n "$value" && -z "${!stripped+x}" ]]; then
                    export "$stripped"="$value"
                fi
                ;;
        esac
    done < "$ENV_FILE"
    # Re-read key values after .env load
    WORKSPACE_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR:-$WORKSPACE_DIR}"
    export WORKSPACE_DIR

    # Re-sync bare-name aliases after .env load.
    # Only sets alias if the bare name wasn't already in the shell env
    # (shell env always takes priority over .env LPB_ values).
    if [[ -z "${EXA_API_KEY+x}" ]]; then
        export EXA_API_KEY="${LPB_EXA_API_KEY}"
    fi
fi

# ─── 2b. RESOLVE PROJECT DIRECTORY (working dir) ────────────────────────────
# The project directory is provided by lpb.py via LPB_DEVCONTAINER_WORKSPACE_DIR,
# which is set to the container mount path (e.g. "/home/lpb/workspace/devstack").
# This is the canonical project identity — lpb.py passes the user's chosen path.
# No need to infer from .env location; lpb.py already resolved it correctly.

PROJECT_DIR="${LPB_DEVCONTAINER_WORKSPACE_DIR}"
export PROJECT_DIR
debug "PROJECT_DIR=$PROJECT_DIR"

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

    mkdir -p "${HOME_DIR}/.pi/agent/git"
    # Pre-create .npmrc so npm reads allow-scripts from parent dir
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > "${HOME_DIR}/.pi/agent/git/.npmrc" 2>/dev/null || true
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > "${HOME_DIR}/.npmrc" 2>/dev/null || true

    # Fix pi-coding-agent package.json to include allowScripts
    # so native addon npm install scripts are not blocked
    PI_PKG="${HOME_DIR}/.npm-global/lib/node_modules/@earendil-works/pi-coding-agent/package.json"
    if [[ -f "$PI_PKG" ]]; then
        # Try jq first, fallback to python
        if command -v jq &>/dev/null; then
            jq '. += {"allowScripts": {"better-sqlite3": true, "agent-browser": true, "esbuild": true, "protobufjs": true, "@google/genai": true}}' "$PI_PKG" > "${PI_PKG}.tmp" && mv "${PI_PKG}.tmp" "$PI_PKG"
        else
            python3 -c "
import json, sys
with open(sys.argv[1]) as f: pkg = json.load(f)
pkg.setdefault('allowScripts', {})
for p in ['better-sqlite3','agent-browser','esbuild','protobufjs','@google/genai']:
    pkg['allowScripts'][p] = True
with open(sys.argv[1], 'w') as f: json.dump(pkg, f, indent=2)
" "$PI_PKG"
        fi
        info "Patched pi-coding-agent package.json with allowScripts."
    fi

    if [[ -d /home/lpb/.local/pi-config ]]; then
        info "Syncing config from /home/lpb/.local/pi-config/..."
        [[ -f /home/lpb/.local/pi-config/settings.json ]] && cp /home/lpb/.local/pi-config/settings.json /home/lpb/.pi/agent/ 2>/dev/null
        [[ -f /home/lpb/.local/pi-config/mcp.json ]] && cp /home/lpb/.local/pi-config/mcp.json /home/lpb/.pi/agent/mcp.json 2>/dev/null && sed -i 's/"directTools": true/"directTools": false/' /home/lpb/.pi/agent/mcp.json 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/lpb-memory-config.json ]] && cp /home/lpb/.local/pi-config/lpb-memory-config.json /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/pi-defaults.json ]] && cp /home/lpb/.local/pi-config/pi-defaults.json /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/subagents.json ]] && cp /home/lpb/.local/pi-config/subagents.json /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/AGENTS.md ]] && cp /home/lpb/.local/pi-config/AGENTS.md /home/lpb/.pi/agent/ 2>/dev/null
        [[ -f /home/lpb/.local/pi-config/SYSTEM.md ]] && cp /home/lpb/.local/pi-config/SYSTEM.md /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -f /home/lpb/.local/pi-config/APPEND_SYSTEM.md ]] && cp /home/lpb/.local/pi-config/APPEND_SYSTEM.md /home/lpb/.pi/agent/ 2>/dev/null || true
        [[ -d /home/lpb/.local/pi-config/skills ]] && cp -r /home/lpb/.local/pi-config/skills/* /home/lpb/.pi/agent/skills/ 2>/dev/null || true
        [[ -d /home/lpb/.local/pi-config/agents ]] && mkdir -p /home/lpb/.pi/agent/agents && (rsync -a --delete /home/lpb/.local/pi-config/agents/ /home/lpb/.pi/agent/agents/ 2>/dev/null || cp -a /home/lpb/.local/pi-config/agents/. /home/lpb/.pi/agent/agents/ 2>/dev/null) || true
        info "Config synced."
    fi

    touch "${HOME_DIR}/.pi/.initialized"

    # ── Unlock the user account with a random password ──────────────────
    # Accounts created without a password have a locked shadow field ('!' or
    # '*'), and OpenSSH rejects ALL authentication (including key-based) for
    # a locked account. Set a random password to unlock it; the user can
    # change it later with `sudo passwd`. Use sudo to read the shadow field
    # (start.sh runs as the non-root user), and only set one when the account
    # has no usable password hash (i.e. locked) so we don't clobber a password
    # intentionally baked in the image. A usable hash always starts with '$'
    # (e.g. $y$ yescrypt).
    _owner="$(stat -c %U "${HOME_DIR}" 2>/dev/null || echo "$(id -un)")"
    _cur="$(sudo -n getent shadow "${_owner}" 2>/dev/null | cut -d: -f2 || true)"
    if command -v chpasswd >/dev/null 2>&1 && [[ -n "${_cur}" && "${_cur}" != \$* ]]; then
        _passwd="$(openssl rand -base64 24)"
        if echo "${_owner}:${_passwd}" | sudo chpasswd 2>/dev/null; then
            info "Unlocked '${_owner}' account (password: ${_passwd}). Change with: sudo passwd"
        else
            _passwd="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "rnd-$(date +%s%N)")"
            if echo "${_owner}:${_passwd}" | chpasswd 2>/dev/null; then
                info "Unlocked '${_owner}' account (password: ${_passwd}). Change with: sudo passwd"
            else
                warn "Could not unlock '${_owner}' account; SSH may be refused."
            fi
        fi
    fi

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

# ─── 5. POST-INIT: NATIVE MODULES ────────────────────────────────────────────

debug "Checking native modules..."
NEED_REBUILD=false
EXT_BASE="${HOME_DIR}/.pi/agent/git"

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
                local_name=$(echo "$ext_dir" | sed "s|.*/agent/git/||")
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

            # Unlock the account if it is locked. Accounts created without a
            # password (e.g. useradd) are locked (shadow field is '!' or '*'), and
            # OpenSSH's checkaccount() rejects ALL authentication — including
            # valid SSH keys — for a locked account. SSH password auth is disabled
            # above, so we assign a random, unusable token purely to un-lock it.
            # Done at runtime so each boot gets a fresh value instead of baking a
            # shared token into the image. Skips if the account already has a
            # password (preserves a password set manually via `sudo passwd`).
            # NOTE: getent shadow must run via sudo — start.sh runs as the
            # non-root user, and reading /etc/shadow (to inspect the lock field)
            # requires root. Without sudo the lookup returns empty/rc=2 and the
            # locked account never gets unlocked, silently breaking SSH key auth.
            # Locked/unusable state includes '!', '!!', '!<hash>', and '*' (set by
            # useradd, usermod -L, or passwd -l). Only a real password hash
            # (starts with '$', e.g. $y$ yescrypt) counts as usable, so base the
            # check on that instead of an exact-match list.
            _owner="$(stat -c %U "${HOME_DIR}" 2>/dev/null || echo "$(id -un)")"
            if [[ -n "${SUDO}" ]] && command -v chpasswd >/dev/null 2>&1; then
                _cur="$(${SUDO} getent shadow "${_owner}" 2>/dev/null | cut -d: -f2)"
                if [[ -n "${_cur}" && "${_cur}" != \$* ]]; then
                    _token="$(cat /proc/sys/kernel/random/uuid 2>/dev/null \
                        || { command -v openssl >/dev/null 2>&1 && openssl rand -hex 16; } \
                        || echo "$(date +%s%N | sha256sum | cut -c1-32)")"
                    if echo "${_owner}:${_token}" | ${SUDO} chpasswd 2>/dev/null; then
                        info "Unlocked '${_owner}' account with random token for SSH key auth (password auth stays disabled)."
                    else
                        warn "Could not unlock '${_owner}' account; SSH key auth may still be refused."
                    fi
                fi
            fi

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
