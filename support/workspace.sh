#!/usr/bin/env bash
# workspace.sh — Manage ~/workspace/ repo symlinks and clones
#
# Usage:
#   ./support/workspace.sh sync        Recreate symlinks + git pull
#   ./support/workspace.sh status      List repos in ~/workspace/
#
# Symlinks → ~/.pi/agent/git/github.com/localpibox/<repo>
# Clones   → ~/workspace/<repo>

set -euo pipefail
cd "$(dirname "$0")/.."

HOME_DIR="${HOME:-/home/lpb}"
WORKSPACE_ROOT="$HOME_DIR/workspace"
AGENT_GIT="${HOME_DIR}/.pi/agent/git/github.com/localpibox"

SYMLINK_REPOS=(lemonade-pi-plugin lpb-memory pi-subagents)
CLONE_REPOS=(pi)

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }

cmd_sync() {
    mkdir -p "$WORKSPACE_ROOT"

    # ── Symlinks ──────────────────────────────────────────────────────────
    for repo in "${SYMLINK_REPOS[@]}"; do
        local src="$AGENT_GIT/$repo" dst="$WORKSPACE_ROOT/$repo"
        if [ -d "$src" ]; then
            rm -f "$dst" 2>/dev/null || true
            ln -s "$src" "$dst"
            info "  $repo → $dst"
        else
            warn "  $repo: source not found at $src"
        fi
    done

    # ── Clones ────────────────────────────────────────────────────────────
    for repo in "${CLONE_REPOS[@]}"; do
        local path="$WORKSPACE_ROOT/$repo"
        if [ -d "$path/.git" ]; then
            git -C "$path" pull --ff-only 2>&1 | tail -1 | sed "s/^/  $repo: /"
        elif [ -d "$path" ]; then
            warn "  $repo: not a git repo"
        else
            warn "  $repo: not found — run: git clone --depth=1 -b lpb \
https://github.com/localpibox/pi.git $path"
        fi
    done
}

cmd_status() {
    echo "=== ~/workspace/ ==="
    for repo in "${SYMLINK_REPOS[@]}"; do
        local path="$WORKSPACE_ROOT/$repo"
        if [ -L "$path" ]; then
            echo "  $repo → $(readlink "$path")"
        else
            echo "  $repo: MISSING (run: $0 sync)"
        fi
    done
    for repo in "${CLONE_REPOS[@]}"; do
        local path="$WORKSPACE_ROOT/$repo"
        if [ -L "$path" ]; then
            echo "  $repo → $(readlink "$path")"
        elif [ -d "$path/.git" ]; then
            local branch
            branch=$(cd "$path" && git branch --show-current 2>/dev/null || echo "?")
            echo "  $repo ($branch)"
        else
            echo "  $repo: MISSING"
        fi
    done
}

case "${1:-help}" in
    sync)     cmd_sync ;;
    status)   cmd_status ;;
    *)        echo "Usage: $0 {sync|status}" >&2; exit 1 ;;
esac
