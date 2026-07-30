#!/usr/bin/env bash
# update.sh — Update extensions, patches, and pi within the container
#
# This script runs INSIDE the container to keep things up-to-date without
# rebuilding the image. It can be invoked via:
#   podman exec -it localpibox /stack.sh update
#
# Usage:
#   ./update.sh [--dry-run] [--extensions] [--patches] [--all]
#
# Options:
#   --dry-run        Show what would be updated without making changes
#   --extensions     Update only pi extensions
#   --patches        Update only git patches
#   --all            Update everything (default)

set -euo pipefail

STACK_DIR="/opt/pi-internal/stack-upkeep"  # Inside container
PI_SRC="/opt/pi-src"  # Inside container
HOME_DIR="/home/dev"

# Color codes
GREEN=$(printf '\033[0;32m')
YELLOW=$(printf '\033[1;33m')
RED=$(printf '\033[0;31m')
CYAN=$(printf '\033[0;36m')
BOLD=$(printf '\033[1m')
NC=$(printf '\033[0m')

DRY_RUN=false
MODE="all"

# ── Parse args ──────────────────────────────────────────────────────────────

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; shift ;;
        --extensions) MODE="extensions"; shift ;;
        --patches)  MODE="patches"; shift ;;
        --all)      MODE="all"; shift ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--extensions|--patches|--all]"
            echo ""
            echo "  --dry-run        Show changes without applying"
            echo "  --extensions     Update pi extensions only"
            echo "  --patches        Update patches only"
            echo "  --all            Update everything (default)"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

print_section() {
    echo ""
    echo -e "${CYAN}${BOLD}=== $1 ===${NC}"
}

print_ok() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${GREEN}✓[DRY]${NC} $1"
    else
        echo -e "  ${GREEN}✓${NC} $1"
    fi
}

print_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
}

print_err() {
    echo -e "  ${RED}✗${NC} $1"
}

# ── Update Extensions ───────────────────────────────────────────────────────

update_extensions() {
    print_section "Extensions"
    
    # Extensions that should be in the container
    # Format: name:repo@branch
    declare -A EXTENSIONS=(
        ["lemonade-provider"]="git:github.com/localpibox/lemonade-pi-plugin@patches/qwen-vision"
        ["pi-hermes-memory"]="git:github.com/localpibox/pi-hermes-memory@fix/subprocess-provider"
        ["pi-mcp-adapter"]="npm:pi-mcp-adapter"
        ["pi-subagents"]="npm:@tintinweb/pi-subagents"
        ["pi-powerline-footer"]="npm:pi-powerline-footer"
    )
    
    if [ "$DRY_RUN" = true ]; then
        echo "  Would ensure these extensions are installed:"
        for name in "${!EXTENSIONS[@]}"; do
            echo "    $name → ${EXTENSIONS[$name]}"
        done
        return 0
    fi
    
    # Install each extension (idempotent)
    for name in "${!EXTENSIONS[@]}"; do
        local pkg="${EXTENSIONS[$name]}"
        echo -n "  Checking $name... "
        
        # Check if extension is already installed and up to date
        if pi list --json 2>/dev/null | grep -q "\"${name}\"" 2>/dev/null || \
           pi list --json 2>/dev/null | grep -q "$(basename "$pkg" | cut -d@ -f1)" 2>/dev/null; then
            echo -e "${GREEN}✓${NC} already installed"
        else
            pi install "$pkg" 2>&1 | tail -1 | sed 's/^/    /'
            echo -e "  ${GREEN}✓${NC} installed"
        fi
    done
}

# ── Update Patches ──────────────────────────────────────────────────────────

update_patches() {
    print_section "Patches"
    
    if [ "$DRY_RUN" = true ]; then
        echo "  Would check and apply patches:"
        echo "    pi-qwen-chat-template.patch"
        echo "    lemonade-qwen-vision.patch"
        echo ""
        echo "  If patches have conflicts, manual intervention needed."
        return 0
    fi
    
    PATCHES_DIR="/opt/pi-patches"
    if [ ! -d "$PATCHES_DIR" ]; then
        print_warn "Patches directory not found"
        return 0
    fi
    
    cd "$PI_SRC" 2>/dev/null || { print_warn "pi-src not found, skipping"; return 0; }
    
    # Check if patches are already applied (by looking at git log)
    local patches_applied=true
    for patch in "$PATCHES_DIR"/*.patch; do
        [ -f "$patch" ] || continue
        local patch_name=$(basename "$patch" .patch)
        if ! git log --oneline --grep="$patch_name" 2>/dev/null | head -1 > /dev/null; then
            patches_applied=false
            break
        fi
    done
    
    if [ "$patches_applied" = true ]; then
        echo -e "  ${GREEN}✓${NC} Patches already applied"
    else
        echo -e "  ${YELLOW}⚠${NC} Applying patches..."
        for patch in "$PATCHES_DIR"/*.patch; do
            [ -f "$patch" ] || continue
            local patch_name=$(basename "$patch" .patch)
            if git am "$patch" 2>&1 >/dev/null; then
                echo -e "  ${GREEN}✓${NC} Applied: $patch_name"
            else
                print_warn "Conflict in: $patch_name — resolve manually"
            fi
        done
        echo ""
        echo -e "  ${YELLOW}⚠${NC} After patch apply, rebuild may be needed:"
        echo "    cd $PI_SRC && npm run build"
    fi
}

# ── Show Status ─────────────────────────────────────────────────────────────

show_status() {
    print_section "Current State"
    
    # Pi version
    if [ -f "$PI_SRC/package.json" ]; then
        local pi_version
        pi_version=$(node -e "console.log(require('$PI_SRC/package.json').version)" 2>/dev/null || echo "unknown")
        echo "  Pi version:   $pi_version"
    else
        echo "  Pi version:   not found"
    fi
    
    # Installed extensions
    echo ""
    echo "  Installed extensions:"
    pi list --json 2>/dev/null | jq -r '.[]?.name // .?.name // "unknown"' 2>/dev/null | while read -r ext; do
        echo "    - $ext"
    done || echo "    (unable to list)"
    
    # Last build date
    if [ -d "$PI_SRC" ]; then
        local build_date
        build_date=$(stat -c '%y' "$PI_SRC/package.json" 2>/dev/null | cut -d. -f1 || echo "unknown")
        echo ""
        echo "  Last build:   $build_date"
    fi
}

# ── Main ────────────────────────────────────────────────────────────────────

echo -e "${BOLD}LocalPibox Stack Update${NC}"
echo "  Mode:    $MODE"
echo "  Dry run: $DRY_RUN"

case "$MODE" in
    extensions) update_extensions ;;
    patches)    update_patches ;;
    all)
        show_status
        update_extensions
        update_patches
        ;;
esac

echo ""
echo -e "${GREEN}${BOLD}Update complete.${NC}"
echo ""
