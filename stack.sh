#!/usr/bin/env bash
# stack.sh — Convenience wrapper for LocalPibox stack upkeep
#
# Usage:
#   ./stack.sh check         — Check upstream repos for new updates
#   ./stack.sh status        — Full stack health check
#   ./stack.sh build         — Rebuild with current settings
#   ./stack.sh rebuild       — Bump version + rebuild
#   ./stack.sh patch         — Show active patches
#   ./stack.sh update        — Update extensions in running container
#   ./stack.sh help          — Show this help
#
# Container backend (auto-detected: podman > docker):
#   Override: export CONTAINER_CMD=podman

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$SCRIPT_DIR/stack-upkeep"
VERSIONS_FILE="$STACK_DIR/versions.env"
ENV_PATCHES="$SCRIPT_DIR/.env-patches"

# Container settings
CONTAINER_CMD="${CONTAINER_CMD:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo docker)}"
CONTAINER_NAME="${CONTAINER_NAME:-localpibox}"
DEFAULT_PORT=3000

# Color codes
GREEN=$(printf '\033[0;32m')
YELLOW=$(printf '\033[1;33m')
CYAN=$(printf '\033[0;36m')
BOLD=$(printf '\033[1m')
NC=$(printf '\033[0m')

# ── Helpers ────────────────────────────────────────────────────────────────

usage() {
    echo -e "${BOLD}LocalPibox Stack Upkeep${NC}"
    echo ""
    echo "  Usage: $0 <command>"
    echo ""
    echo "  Commands:"
    echo "    check        Check upstream repos for new updates"
    echo "    status       Full stack health check"
    echo "    build        Rebuild container with current versions"
    echo "    rebuild      Bump version + rebuild"
    echo "    patch        Show active patches"
    echo "    update       Update extensions in running container"
    echo "    help         Show this help"
    echo ""
    echo "  Container backend (auto-detected):"
    echo "    podman preferred on Fedora/Ubuntu, docker on macOS/Windows"
    echo ""
    echo "  Override: export CONTAINER_CMD=podman"
    echo ""
    echo "  Examples:"
    echo "    $0 check              # See what's behind upstream"
    echo "    $0 rebuild            # New upstream release? bump + rebuild"
    echo "    $0 status             # Validate everything is ready"
    echo "    $0 update             # Update extensions in container"
}

source_versions() {
    if [ -f "$VERSIONS_FILE" ]; then
        while IFS='=' read -r key value; do
            [[ "$key" =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            value=$(echo "$value" | sed 's/^"//;s/"$//')
            export "$key"="$value"
        done < "$VERSIONS_FILE"
        # Also sync .env-patches for container build
        grep -v '^#' "$VERSIONS_FILE" | grep -v '^$' | grep '=' > "$ENV_PATCHES" 2>/dev/null || true
    fi
}

build_cmd() {
    source_versions
    # Auto-detect container command (podman preferred)
    local CMD="${CONTAINER_CMD:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo docker)}"
    echo -e "${CYAN}Building with $CMD...${NC}"
    cd "$SCRIPT_DIR"
    $CMD build -t ghcr.io/localpibox/devstack:latest .
}

rebuild_cmd() {
    source_versions
    
    local PI_PATCH_VER="${pi_patch_version:-20260730-001}"
    local LEMONADE_PATCH_VER="${lemonade_patch_version:-20260730-001}"
    
    # Bump counters
    local PI_DATE="${PI_PATCH_VER%%-*}"
    local PI_COUNTER=$(echo "$PI_PATCH_VER" | cut -d- -f2 | sed 's/^0*//')
    local LEMONADE_DATE="${LEMONADE_PATCH_VER%%-*}"
    local LEMONADE_COUNTER=$(echo "$LEMONADE_PATCH_VER" | cut -d- -f2 | sed 's/^0*//')
    
    local PI_NEW="${PI_DATE}-$(printf '%03d' $((PI_COUNTER + 1)))"
    local LEMONADE_NEW="${LEMONADE_DATE}-$(printf '%03d' $((LEMONADE_COUNTER + 1)))"
    
    # Update versions.env and .env-patches
    sed -i "s/^pi_patch_version=.*/pi_patch_version=$PI_NEW/" "$VERSIONS_FILE"
    sed -i "s/^lemonade_patch_version=.*/lemonade_patch_version=$LEMONADE_NEW/" "$VERSIONS_FILE"
    grep -v '^#' "$VERSIONS_FILE" | grep -v '^$' | grep '=' > "$ENV_PATCHES" 2>/dev/null || true
    
    # Auto-detect container command (podman preferred)
    local CMD="${CONTAINER_CMD:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo docker)}"
    
    echo -e "${CYAN}Versions bumped:${NC}"
    echo "  Pi:      $PI_PATCH_VER → $PI_NEW"
    echo "  Lemonade: $LEMONADE_PATCH_VER → $LEMONADE_NEW"
    echo ""
    echo -e "${CYAN}Rebuilding with $CMD...${NC}"
    
    cd "$SCRIPT_DIR"
    $CMD build -t ghcr.io/localpibox/devstack:latest .
}

patch_cmd() {
    echo -e "${BOLD}Active Patches${NC}"
    echo ""
    
    echo -e "${CYAN}── Pi ─────────────────────────────────────────────────────${NC}"
    for p in "$STACK_DIR/patches"/pi-*.patch; do
        [ -f "$p" ] || continue
        local name=$(basename "$p" .patch)
        local lines=$(wc -l < "$p")
        echo "  $name ($lines lines)"
        echo ""
        head -3 "$p" | sed 's/^/    /'
    done
    
    echo ""
    echo -e "${CYAN}── Lemonade ───────────────────────────────────────────────${NC}"
    for p in "$STACK_DIR/patches"/lemonade-*.patch; do
        [ -f "$p" ] || continue
        local name=$(basename "$p" .patch)
        local lines=$(wc -l < "$p")
        echo "  $name ($lines lines)"
        echo ""
        head -3 "$p" | sed 's/^/    /'
    done
}

update_cmd() {
    source_versions
    
    # Auto-detect container command
    local CMD="${CONTAINER_CMD:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo docker)}"
    
    # Check if container is running
    if ! $CMD ps --format '{{.Names}}' 2>/dev/null | grep -q "$CONTAINER_NAME"; then
        echo -e "${YELLOW}⚠ Container '$CONTAINER_NAME' is not running.${NC}"
        echo ""
        echo "  Options:"
        echo "  1. Run: $CMD run -d --name $CONTAINER_NAME <image>"
        echo "  2. Or use: ./run.sh /path/to/project"
        echo ""
        echo "  Once running, you can:"
        echo "    $CMD exec -it $CONTAINER_NAME /opt/pi-patches/update.sh --extensions"
        exit 1
    fi
    
    # Run the update script inside the container
    echo -e "${CYAN}Running update inside container...${NC}"
    $CMD exec -it "$CONTAINER_NAME" /opt/pi-patches/update.sh "$@"
}

status_cmd() {
    source_versions
    exec "$STACK_DIR/scripts/validate-status.sh"
}

check_cmd() {
    source_versions
    exec "$STACK_DIR/scripts/check-updates.sh"
}

# ── Main ───────────────────────────────────────────────────────────────────

cmd="${1:-help}"
case "$cmd" in
    check)    check_cmd ;;
    status)   status_cmd ;;
    build)    build_cmd ;;
    rebuild)  rebuild_cmd ;;
    patch)    patch_cmd ;;
    update)   update_cmd ;;
    help)     usage ;;
    *)        usage; exit 1 ;;
esac
