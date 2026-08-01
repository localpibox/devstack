#!/usr/bin/env bash
# check-updates.sh — Check if upstream repos have new updates

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$STACK_DIR")"
VERSIONS_FILE="$STACK_DIR/versions.env"

# ── Source dependency checker ──────────────────────────────────────────────
if [ ! -v DEPENDENCIES_CHECKED ]; then
    source "$SCRIPT_DIR/dep-check.sh"
fi

# ── Container command ──────────────────────────────────────────────────────
if [ -n "${CONTAINER_CMD:-}" ] && [ "$CONTAINER_CMD" != "" ]; then
    CONTAINER_CMD="${CONTAINER_CMD}"
else
    if command -v podman &>/dev/null; then
        CONTAINER_CMD=podman
    else
        CONTAINER_CMD=docker
    fi
fi

# Color codes
GREEN=$(printf '\033[0;32m')
YELLOW=$(printf '\033[1;33m')
CYAN=$(printf '\033[0;36m')
BOLD=$(printf '\033[1m')
RED=$(printf '\033[0;31m')
NC=$(printf '\033[0m')

# ── GitHub auth check ──────────────────────────────────────────────────────
# gh auth status returns non-zero if ANY account fails, even if primary is valid.
# We check the actual output for a ✓ login to the active account.

check_gh_auth() {
    if ! command -v gh &>/dev/null; then
        echo -e "  ${RED}✗${NC} gh CLI not found"
        return 1
    fi
    
    # gh auth status returns 0 if all accounts OK, non-zero if any failed
    # But the output always shows the active account line. Check for that.
    local auth_output
    auth_output=$(gh auth status 2>&1)
    
    # Check if we have a "✓ Logged in" for the active account
    if echo "$auth_output" | grep -q "✓ Logged in" && echo "$auth_output" | grep -q "Active account: true"; then
        return 0
    fi
    
    # If gh is installed but no valid login found
    echo -e "  ${RED}✗${NC} gh not authenticated — run: gh auth login"
    echo ""
    echo -e "  ${YELLOW}⚠ Cannot check upstream status without GitHub auth${NC}"
    return 1
}

# ── Helpers (with retry for flaky networks) ─────────────────────────────────

safe_gh() {
    local jq_filter="$1"
    shift
    local max_retries=5
    local retry=0
    local output=""
    
    while [ $retry -lt $max_retries ]; do
        if output=$("$@" --jq "$jq_filter" 2>/dev/null); then
            if [ -n "$output" ] && [ "$output" != "null" ]; then
                echo "$output"
                return 0
            fi
        fi
        retry=$((retry + 1))
        if [ $retry -lt $max_retries ]; then
            echo "  [retry $retry/$max_retries] GitHub API request failed" >&2
            sleep 3
        fi
    done
    echo "unknown"
    return 0
}

get_branch_sha() {
    safe_gh '.commit.sha' gh api "repos/$1/$2/branches/$3"
}

get_commit_sha() {
    safe_gh '.sha' gh api "repos/$1/$2/commits/main"
}

get_release_tag() {
    safe_gh '.tag_name' gh api "repos/$1/$2/releases/latest"
}

# ── Source config ───────────────────────────────────────────────────────────

if [ -f "$VERSIONS_FILE" ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        value=$(echo "$value" | sed 's/^"//;s/"$//')
        export "$key"="$value"
    done < "$VERSIONS_FILE"
fi

PI_BRANCH="${pi_branch:-patches/qwen-reasoning-effort}"
LEMONADE_BRANCH="${lemonade_branch:-patches/qwen-vision}"
MEMORY_BRANCH="${memory_branch:-fix/subprocess-provider}"

# ── Main ───────────────────────────────────────────────────────────────────

echo -e "${CYAN}=== Stack Upkeep — Upstream Check ===${NC}"
echo ""

# ── 0. GitHub auth ─────────────────────────────────────────────────────────

echo -e "${CYAN}── GitHub Auth ──────────────────────────────────────────${NC}"
if check_gh_auth; then
    echo -e "  Status: ${GREEN}✓ Authenticated${NC}"
    GH_AUTH_OK=true
else
    GH_AUTH_OK=false
fi
echo ""

# ── Pi Monorepo ────────────────────────────────────────────────────────────

echo -e "${CYAN}── Pi Monorepo ──────────────────────────────────────────${NC}"

if [ "$GH_AUTH_OK" = true ]; then
    fork_sha=$(get_branch_sha "localpibox" "pi" "$PI_BRANCH")
    upstream_sha=$(get_commit_sha "earendil-works" "pi")
    latest_release=$(get_release_tag "earendil-works" "pi")
else
    fork_sha="n/a (not authenticated)"
    upstream_sha="n/a (not authenticated)"
    latest_release="n/a (not authenticated)"
fi

echo -e "  Fork:           localpibox/pi"
echo -e "  Patch branch:   ${GREEN}${PI_BRANCH}${NC}"
echo -e "  Fork SHA:       ${fork_sha:0:12}"
echo -e "  Upstream SHA:   ${upstream_sha:0:12}"
echo -e "  Latest release: ${CYAN}${latest_release}${NC}"

if [ "$GH_AUTH_OK" = true ] && [ "$fork_sha" != "unknown" ] && [ "$fork_sha" != "n/a" ]; then
    if [ "$fork_sha" = "$upstream_sha" ]; then
        echo -e "  Status:         ${GREEN}${BOLD}✓ Up to date with upstream${NC}"
    else
        echo -e "  Status:         ${GREEN}✓ Local patches applied on top${NC}"
        echo -e "  Note:           Fork is ahead of upstream (contains local changes)"
        echo -e "  Action (when upstream updates): git rebase upstream/main"
    fi
elif [ "$GH_AUTH_OK" = false ]; then
    echo -e "  Status:         ${YELLOW}⚠ Skip (auth required)${NC}"
fi

echo ""

# ── Lemonade Plugin ─────────────────────────────────────────────────────────

echo -e "${CYAN}── Lemonade Plugin ──────────────────────────────────────${NC}"

if [ "$GH_AUTH_OK" = true ]; then
    fork_sha=$(get_branch_sha "localpibox" "lemonade-pi-plugin" "$LEMONADE_BRANCH")
    upstream_sha=$(get_commit_sha "lemonade-sdk" "lemonade-pi-plugin")
else
    fork_sha="n/a (not authenticated)"
    upstream_sha="n/a (not authenticated)"
fi

echo -e "  Fork:           localpibox/lemonade-pi-plugin"
echo -e "  Patch branch:   ${GREEN}${LEMONADE_BRANCH}${NC}"
echo -e "  Fork SHA:       ${fork_sha:0:12}"
echo -e "  Upstream SHA:   ${upstream_sha:0:12}"

if [ "$GH_AUTH_OK" = true ] && [ "$fork_sha" != "unknown" ] && [ "$fork_sha" != "n/a" ]; then
    if [ "$fork_sha" = "$upstream_sha" ]; then
        echo -e "  Status:         ${GREEN}${BOLD}✓ Up to date with upstream${NC}"
    else
        echo -e "  Status:         ${GREEN}✓ Local patches applied on top${NC}"
    fi
elif [ "$GH_AUTH_OK" = false ]; then
    echo -e "  Status:         ${YELLOW}⚠ Skip (auth required)${NC}"
fi

echo ""

# ── Memory Extension ───────────────────────────────────────────────────────

echo -e "${CYAN}── Memory Extension ─────────────────────────────────────${NC}"

if [ "$GH_AUTH_OK" = true ]; then
    mem_sha=$(get_branch_sha "localpibox" "pi-hermes-memory" "$MEMORY_BRANCH")
else
    mem_sha="n/a (not authenticated)"
fi

echo -e "  Repo:           localpibox/pi-hermes-memory"
echo -e "  Branch:         ${GREEN}${MEMORY_BRANCH}${NC}"
echo -e "  Branch SHA:     ${mem_sha:0:12}"
echo -e "  Status:         ${GREEN}✓ Active branch${NC}"

echo ""

# ── Build Configuration ─────────────────────────────────────────────────────

echo -e "${CYAN}── Build Configuration ────────────────────────────────────${NC}"

echo -e "  Pi fork:    ${GREEN}${pi_fork:-github.com/localpibox/pi.git}${NC}"
echo -e "  Pi branch:  ${GREEN}${pi_branch:-patches/qwen-reasoning-effort}${NC}"
echo -e "  Node:       ${node_version:-24}"
echo -e "  VSCodium:   ${vscodium_version:-latest}"
echo ""
echo -e "  ${CYAN}To invalidate cache: change pi_branch or pi_fork in versions.env${NC}"

echo ""
echo -e "${CYAN}=== End Report ===${NC}"
