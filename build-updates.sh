#!/usr/bin/env bash
# build-updates.sh — Build tarballs for container updates
#
# Usage:
#   ./build-updates.sh                     # Build all tarballs
#   ./build-updates.sh --push              # Build and push to GHCR
#   ./build-updates.sh --help
#
# Tarballs produced:
#   updates/pi-<sha>.tar.gz        — Patched pi packages
#   updates/lemonade-<sha>.tar.gz  — Lemonade plugin
#   updates/memory-<sha>.tar.gz    — Memory extension
#   updates/config-<sha>.tar.gz    — Project config

set -euo pipefail

OUTPUT_DIR="updates"
BUILD_DIR="/tmp/localpibox-build"

# Color codes
GREEN=$(printf '\033[0;32m')
CYAN=$(printf '\033[0;36m')
NC=$(printf '\033[0m')

push=false

while [ $# -gt 0 ]; do
    case "$1" in
        --push) push=true; shift ;;
        --help|-h)
            echo "Usage: $0 [--push]"
            echo ""
            echo "Build tarballs for container updates."
            echo "Tarballs are stored in $OUTPUT_DIR/ and can be loaded"
            echo "into a running container via: stack.sh update"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$OUTPUT_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

build_tarball() {
    local name="$1"
    local src="$2"
    local label="$3"
    
    echo -e "${CYAN}Building $label tarball...${NC}"
    
    local sha=$(git -C "$src" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    local tag="${name}-${sha}"
    local tarball="$OUTPUT_DIR/${tag}.tar.gz"
    
    # Build tarball with proper ownership
    (cd "$src" && tar czf "$tarball" --owner=1000 --group=1000 -C . $(git ls-files 2>/dev/null || ls -1))
    
    echo -e "  ${GREEN}✓${NC} Created $tarball"
}

# ── Build pi tarball ───────────────────────────────────────────────────────
PI_DIR="$BUILD_DIR/pi"
git clone --depth=1 --branch main https://github.com/earendil-works/pi "$PI_DIR" 2>/dev/null
cd "$PI_DIR"
git remote add localpibox https://github.com/localpibox/pi.git
git fetch localpibox 2>/dev/null
# Apply patches
for patch in stack-upkeep/patches/pi-*.patch; do
    [ -f "$patch" ] || continue
    git am "$patch" 2>/dev/null || true
done
build_tarball "pi" "$PI_DIR" "Pi monorepo"

# ── Build lemonade tarball ─────────────────────────────────────────────────
LEMONADE_DIR="$BUILD_DIR/lemonade"
git clone --depth=1 --branch patches/qwen-vision https://github.com/localpibox/lemonade-pi-plugin "$LEMONADE_DIR" 2>/dev/null
build_tarball "lemonade" "$LEMONADE_DIR" "Lemonade plugin"

# ── Build memory tarball ──────────────────────────────────────────────────
MEMORY_DIR="$BUILD_DIR/memory"
git clone --depth=1 --branch fix/subprocess-provider https://github.com/localpibox/pi-hermes-memory "$MEMORY_DIR" 2>/dev/null
build_tarball "memory" "$MEMORY_DIR" "Memory extension"

# ── Build config tarball ──────────────────────────────────────────────────
CONFIG_DIR="$BUILD_DIR/config"
git clone --depth=1 https://github.com/localpibox/config "$CONFIG_DIR" 2>/dev/null
build_tarball "config" "$CONFIG_DIR" "Project config"

echo ""
echo -e "${GREEN}Tarballs built in $OUTPUT_DIR/:${NC}"
ls -lh "$OUTPUT_DIR/"/*.tar.gz 2>/dev/null || echo "  (none)"
echo ""

if [ "$push" = true ]; then
    echo "Pushing to GHCR..."
    # Configure GHCR push (requires gh auth)
    IMAGE="ghcr.io/localpibox/devstack-updates"
    CONTAINER_CMD="${CONTAINER_CMD:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo docker)}"
    for tarball in "$OUTPUT_DIR"/*.tar.gz; do
        name=$(basename "$tarball" .tar.gz)
        $CONTAINER_CMD tag "$tarball" "$IMAGE:$name" 2>/dev/null || true
        $CONTAINER_CMD push "$IMAGE:$name" 2>/dev/null || echo "  ⚠ Push failed for $name"
    done
fi
