# /opt/pi-support/_lib.sh — Shared helpers for devstack support scripts
# Sourced by: start.sh, lpb-config, validate.sh, install-browser.sh, install-openspec.sh
# Defines: parse_env_file, migrate_layout, _unlock_account
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════
# parse_env_file <path>
# — Reads a KEY=VALUE .env/.conf file, skipping comments, blanks, and
#   lines without '='. Output is one 'key=value' line per entry with
#   trimmed whitespace.
# Usage:   while IFS= read -r _line; do … done < <(parse_env_file "$FILE")
# ═══════════════════════════════════════════════════════════════════════
parse_env_file() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments, blank lines, and lines without '='
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        [[ "$line" != *=* ]] && continue
        local key val
        key="${line%%=*}"
        val="${line#*=}"
        # Trim leading/trailing whitespace
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        val="${val#"${val%%[![:space:]]*}"}"
        val="${val%"${val##*[![:space:]]}"}"
        echo "${key}=${val}"
    done < "$file"
}

# ═══════════════════════════════════════════════════════════════════════
# _migrate_legacy_layout <pi_root> <agent_dir> <log_func>
# — Moves legacy ~/.pi root layout contents into ~/.pi/agent/ (one-time).
#   Preserves: .initialized, ssh-host-keys, gh-config, agent/
# Usage:   _migrate_legacy_layout "$HOME_DIR/.pi" "$AGENT_DIR" info
# ═══════════════════════════════════════════════════════════════════════
_migrate_legacy_layout() {
    local pi_root="$1" agent_dir="$2" log_func="${3:-echo}"
    if [[ -d "${pi_root}/.git" && ! -d "${agent_dir}/.git" ]]; then
        "$log_func" "Migrating legacy config layout from $pi_root to $agent_dir ..."
        mkdir -p "${agent_dir}"
        shopt -s dotglob nullglob
        for _item in "${pi_root}"/*; do
            case "$(basename "${_item}")" in
                .initialized|ssh-host-keys|gh-config|agent) continue ;;
            esac
            mv "${_item}" "${agent_dir}/" 2>/dev/null || true
        done
        shopt -u dotglob nullglob
        "$log_func" "Legacy config layout migrated to ${agent_dir}."
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# _unlock_account <owner> <sudo_cmd> <log_func>
# — Unlocks a locked user account (shadow field starts with ! or *) so
#   SSH key auth works. Generates one random non-usable token per invocation
#   — never baked into the image.
# Usage:   _unlock_account "lpb" "sudo -n" info   # in start.sh
#          _unlock_account "lpb" "sudo -n" warn    # lpb-config fallback
# ═══════════════════════════════════════════════════════════════════════
_unlock_account() {
    local owner="$1" sudo_cmd="${2:-sudo -n}" log_func="${3:-echo}"
    if ! command -v chpasswd >/dev/null 2>&1; then
        return 0
    fi
    local cur
    cur="$(${sudo_cmd} getent shadow "$owner" 2>/dev/null | cut -d: -f2)" || true
    # A locked account has ! or * in the shadow hash; a real password starts with $
    if [[ -n "$cur" && "$cur" != \$* ]]; then
        # Use the most-reliable random source available
        local token
        token="$(openssl rand -base64 24 2>/dev/null)" || \
        token="$(cat /proc/sys/kernel/random/uuid 2>/dev/null)" || \
        token="rnd-$RANDOM"
        # Try sudo first, then non-sudo as fallback
        echo "${owner}:${token}" | ${sudo_cmd} chpasswd 2>/dev/null && {
            $log_func "Unlocked '${owner}' account. Change with: sudo passwd"
            return 0
        } || echo "${owner}:${token}" | chpasswd 2>/dev/null && {
            $log_func "Unlocked '${owner}' account. Change with: sudo passwd"
            return 0
        }
        $log_func "Could not unlock '${owner}' account; login may be refused."
    fi
}
