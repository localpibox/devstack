#!/usr/bin/env bash
# version.sh — LocalPibox stack version management
#
# Single entry point to orchestrate versioning across all 6 stack repos.
#
# Usage:
#   ./support/version.sh status              Show all repo versions
#   ./support/version.sh validate            Validate repo state
#
#   ./support/version.sh patch               Bump patch (1.0.0-lpb → 1.0.1-lpb)
#   ./support/version.sh minor               Bump minor (1.0.0-lpb → 1.1.0-lpb)
#   ./support/version.sh major               Bump major (1.0.0-lpb → 2.0.0-lpb)
#
#   ./support/version.sh tag <version>       Create matching git tags on all repos
#   ./support/version.sh push-tags           Push all tags to remote
#   ./support/version.sh update-ref <ver>    Update LPB_PI_REF in lpb.stack.env
#   ./support/version.sh update-pins <ver>   Update settings.json package pins
#   ./support/version.sh workspace sync      Sync workspace/ symlinks
#
# Examples:
#   ./support/version.sh status
#   ./support/version.sh patch    # auto-bumps patch, tags, updates env/pins
#   ./support/version.sh minor    # auto-bumps minor, tags, updates env/pins
#   ./support/version.sh major    # auto-bumps major, tags, updates env/pins

set -euo pipefail
cd "$(dirname "$0")/.."

# ─── Repo definitions ────────────────────────────────────────────────────────
declare -a REPOS=(
    "pi:/home/lpb/workspace/localpibox/devstack/workspace/pi:lpb"
    "lemonade-pi-plugin:/home/lpb/.pi/agent/git/github.com/localpibox/lemonade-pi-plugin:lpb"
    "config:/home/lpb/workspace/localpibox/config:main"
    "devstack:/home/lpb/workspace/localpibox/devstack:main"
    "pi-subagents:/home/lpb/.pi/agent/git/github.com/localpibox/pi-subagents:lpb"
    "lpb-memory:/home/lpb/workspace/localpibox/lpb-memory:main"
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }

repo_path() {
    local repo="$1"
    local entry
    for entry in "${REPOS[@]}"; do
        [ "${entry%%:*}" = "$repo" ] || continue
        echo "$entry" | cut -d: -f2
        return
    done
}

# ─── Version detection & increment ──────────────────────────────────────────

detect_version() {
    # Read version from repo root VERSION file (the anchor repo)
    cat VERSION 2>/dev/null || echo "0.0.0-lpb"
}

get_base() {
    # Extract base suffix (e.g., "-lpb" from "1.0.1-lpb")
    local ver="$1"
    echo "$ver" | sed 's/^[0-9]*\.[0-9]*\.[0-9]*//'
}

get_major() {
    local ver="$1"
    echo "$ver" | sed 's/^\([0-9]*\)\..*/\1/'
}

get_minor() {
    local ver="$1"
    echo "$ver" | sed 's/^[0-9]*\.\([0-9]*\)\..*/\1/'
}

get_patch() {
    local ver="$1"
    echo "$ver" | sed 's/^[0-9]*\.[0-9]*\.\([0-9]*\).*/\1/'
}

increment_version() {
    local bump_type="$1"  # patch, minor, major
    local ver
    ver=$(detect_version)
    local base major minor patch
    base=$(get_base "$ver")
    major=$(get_major "$ver")
    minor=$(get_minor "$ver")
    patch=$(get_patch "$ver")

    case "$bump_type" in
        patch)
            patch=$((patch + 1))
            ;;
        minor)
            minor=$((minor + 1))
            patch=0
            ;;
        major)
            major=$((major + 1))
            minor=0
            patch=0
            ;;
        *)
            error "Unknown bump type: $bump_type"
            exit 1
            ;;
    esac

    echo "${major}.${minor}.${patch}${base}"
}

# ─── Core operations ────────────────────────────────────────────────────────

bump_all() {
    local ver="$1"
    info "Bumping all repos to $ver"

    for entry in "${REPOS[@]}"; do
        local repo="${entry%%:*}"
        local path
        path=$(echo "$entry" | cut -d: -f2)
        [ -d "$path" ] || continue

        # Update VERSION file
        if [ -f "$path/VERSION" ]; then
            echo "$ver" > "$path/VERSION"
            info "  $repo: VERSION $ver"
        fi

        # Update package.json version
        if [ -f "$path/package.json" ]; then
            python3 -c "
import json, sys
with open('$path/package.json') as f:
    d = json.load(f)
d['version'] = '$ver'
with open('$path/package.json', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" 2>/dev/null && info "  $repo: package.json $ver"
        fi
    done
}

tag_all() {
    local ver="$1"
    info "Creating tags on all repos: $ver"

    for entry in "${REPOS[@]}"; do
        local repo="${entry%%:*}"
        local path
        path=$(echo "$entry" | cut -d: -f2)
        [ -d "$path" ] || continue

        # Skip if tag exists
        if git -C "$path" tag -l 2>/dev/null | grep -qx "$ver"; then
            info "  $repo: tag $ver already exists"
            continue
        fi

        git -C "$path" tag -a "$ver" -m "Stack version $ver" 2>/dev/null && \
            info "  $repo: tagged $ver"
    done
}

update_env_and_pins() {
    local ver="$1"

    # Update LPB_PI_REF in lpb.stack.env
    if [ -f "lpb.stack.env" ]; then
        sed -i "s/^LPB_PI_REF=.*/LPB_PI_REF=$ver/" lpb.stack.env
        info "  Updated lpb.stack.env: LPB_PI_REF=$ver"
    fi

    # Update settings.json package pins
    local settings="/home/lpb/.pi/agent/settings.json"
    if [ -f "$settings" ]; then
        python3 -c "
import json
with open('$settings') as f:
    d = json.load(f)
pins = {
    'lemonade-pi-plugin': 'git:github.com/localpibox/lemonade-pi-plugin@$ver',
    'lpb-memory': 'git:github.com/localpibox/lpb-memory@$ver',
    'pi-subagents': 'git:github.com/localpibox/pi-subagents@$ver',
}
for old in d.get('packages', []):
    for name, new in pins.items():
        if name in old:
            idx = d['packages'].index(old)
            d['packages'][idx] = new
            print(f'  settings.json: {old} -> {new}')
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" 2>/dev/null
    fi
}

# ─── Commands ────────────────────────────────────────────────────────────────

cmd_status() {
    echo "=== LocalPibox Stack Versions ==="
    echo ""
    for entry in "${REPOS[@]}"; do
        local repo="${entry%%:*}"
        local path
        path=$(echo "$entry" | cut -d: -f2)
        local expected_branch
        expected_branch=$(echo "$entry" | cut -d: -f3)

        if [ ! -d "$path" ]; then
            echo "  $repo: NOT FOUND ($path)"
            continue
        fi

        local branch_name tags commits version_file pkg_json
        branch_name=$(cd "$path" && git branch --show-current 2>/dev/null || echo "?")
        tags=$(cd "$path" && git tag -l | head -5 | tr '\n' ' ' || echo "(none)")
        commits=$(cd "$path" && git rev-list --count HEAD 2>/dev/null || echo "?")
        version_file=""
        [ -f "$path/VERSION" ] && version_file=$(cat "$path/VERSION")
        pkg_json=""
        [ -f "$path/package.json" ] && pkg_json=$(python3 -c "import json;print(json.load(open('$path/package.json')).get('version','?'))" 2>/dev/null || echo "?")

        echo "  $repo"
        echo "    Branch: $branch_name"
        echo "    Tags:   $tags"
        echo "    Commits: $commits"
        [ -n "$version_file" ] && echo "    VERSION: $version_file"
        [ -n "$pkg_json" ] && [ "$pkg_json" != "?" ] && echo "    package.json: $pkg_json"
        echo ""
    done
    echo ""

    # Current version
    echo "Current stack version: $(detect_version)"
    if [ -f "lpb.stack.env" ]; then
        echo "  LPB_PI_REF: $(grep '^LPB_PI_REF=' lpb.stack.env | cut -d= -f2)"
    fi
}

cmd_validate() {
    local errors=0

    info "Validating stack repos"
    echo ""

    for entry in "${REPOS[@]}"; do
        local repo="${entry%%:*}"
        local path expected_branch
        path=$(echo "$entry" | cut -d: -f2)
        expected_branch=$(echo "$entry" | cut -d: -f3)

        if [ ! -d "$path" ]; then
            echo "  ✗ $repo: NOT FOUND at $path"
            errors=$((errors + 1))
            continue
        fi

        local branch
        branch=$(cd "$path" && git branch --show-current 2>/dev/null || echo "unknown")
        if [ "$branch" != "$expected_branch" ]; then
            echo "  ⚠ $repo: on '$branch' (expected '$expected_branch')"
        else
            echo "  ✓ $repo: on $branch"
        fi

        local dirty
        dirty=$(cd "$path" && git status --porcelain 2>/dev/null | wc -l)
        [ "$dirty" -gt 0 ] && echo "    ⚠ $dirty uncommitted change(s)"
    done

    echo ""
    echo "=== Git tracking ==="
    local tracked_ws
    tracked_ws=$(git ls-files workspace/ 2>/dev/null | grep -v '.gitignore' | wc -l)
    if [ "$tracked_ws" -gt 0 ]; then
        echo "  ✗ $tracked_ws file(s) in workspace/ tracked by git (should be ignored)"
        errors=$((errors + 1))
    else
        echo "  ✓ workspace/ files not tracked"
    fi

    echo ""
    if [ "$errors" -gt 0 ]; then
        echo "Found $errors issue(s). See above for details."
    else
        echo "All checks passed."
    fi
}

# ─── Main ────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $0 <command> [args]

Stack versioning for LocalPibox repos.

Commands:
  status                Show all repo versions and current stack version
  validate              Validate repo state (branches, tracking)
  patch                 Auto-bump patch, update all, tag, update env/pins
  minor                 Auto-bump minor, update all, tag, update env/pins
  major                 Auto-bump major, update all, tag, update env/pins
  tag <version>         Create matching git tags on all repos
  push-tags             Push all tags to remotes
  update-ref <version>  Update LPB_PI_REF in lpb.stack.env
  update-pins <version> Update settings.json package pins
  workspace sync        Sync workspace/ symlinks to ~/.pi/agent/git/

Examples:
  $0 status
  $0 patch    # reads current version, bumps patch, updates everything
  $0 minor
  $0 major
EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
    status)    cmd_status ;;
    validate)  cmd_validate ;;

    patch|minor|major)
        NEW_VER=$(increment_version "$cmd")
        info "Bumping $cmd version: $(detect_version) → $NEW_VER"
        bump_all "$NEW_VER"
        tag_all "$NEW_VER"
        update_env_and_pins "$NEW_VER"
        info "Done. Review changes and commit."
        ;;

    tag)          [ -n "${1:-}" ] && tag_all "$1" || { error "Usage: $0 tag <version>"; exit 1; } ;;
    push-tags)    echo "Push tags manually on each repo (no remotes configured in version.sh)" ;;
    update-ref)   [ -n "${1:-}" ] && update_env_and_pins "$1" || { error "Usage: $0 update-ref <version>"; exit 1; } ;;
    update-pins)  [ -n "${1:-}" ] && update_env_and_pins "$1" || { error "Usage: $0 update-pins <version>"; exit 1; } ;;
    workspace)    [ "${1:-}" = "sync" ] && (
        local ws="workspace"
        local agent_git="/home/lpb/.pi/agent/git/github.com/localpibox"
        mkdir -p "$ws"
        for repo in lemonade-pi-plugin lpb-memory pi-subagents; do
            local src="$agent_git/$repo" dst="$ws/$repo"
            [ -d "$src" ] && { rm -rf "$dst" 2>/dev/null || true; ln -s "$src" "$dst"; }
        done
    ) || { error "Usage: $0 workspace sync"; exit 1; } ;;

    help|-h|--help) usage ;;
    *)            error "Unknown command: $cmd"; usage; exit 1 ;;
esac
