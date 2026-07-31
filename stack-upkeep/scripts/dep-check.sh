#!/usr/bin/env bash
# dep-check.sh — Verify required tools are available
#
# Usage: source ./stack-upkeep/scripts/dep-check.sh
#
# Returns: sets MISSING_TOOLS and WARNINGS arrays
# Exit: 1 if missing required tools, 0 otherwise

# ── Required tools ─────────────────────────────────────────────────────────
REQUIRED_TOOLS=(bash git)

# ── Optional tools ─────────────────────────────────────────────────────────
OPTIONAL_WARNINGS=(
    "podman or docker required for container builds"
    "jq required for gh API calls (install jq)"
)

MISSING_TOOLS=()
WARNINGS=()

# ── Check function ─────────────────────────────────────────────────────────

check_tool() {
    if ! command -v "$1" &>/dev/null; then
        MISSING_TOOLS+=("$1")
    fi
}

# ── Run checks ─────────────────────────────────────────────────────────────

# Required
for tool in "${REQUIRED_TOOLS[@]}"; do
    check_tool "$tool"
done

# Container runtime (podman or docker required)
if ! command -v podman &>/dev/null && ! command -v docker &>/dev/null; then
    WARNINGS+=("podman or docker required for container builds")
fi

# gh requires jq
if command -v gh &>/dev/null && ! command -v jq &>/dev/null; then
    WARNINGS+=("jq required for gh API calls (install jq)")
fi

# ── Output ─────────────────────────────────────────────────────────────────

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo ""
    echo -e "\033[0;31m✗ Missing required tools:\033[0m"
    for tool in "${MISSING_TOOLS[@]}"; do
        echo -e "  \033[0;31m✗\033[0m $tool"
    done
    echo ""
    echo "Install them before running stack commands."
    return 1 2>/dev/null || exit 1
fi

if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo ""
    echo -e "\033[1;33m⚠ Missing optional tools (some features may not work):\033[0m"
    for warn in "${WARNINGS[@]}"; do
        echo -e "  \033[1;33m⚠\033[0m $warn"
    done
    echo ""
fi

# When sourced, do NOT call exit — use return instead
return 0
