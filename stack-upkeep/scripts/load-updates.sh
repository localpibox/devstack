#!/usr/bin/env bash
# load-updates.sh — Load update tarballs into the running container
#
# This script runs INSIDE the container. It loads update tarballs
# without requiring a rebuild.
#
# Usage:
#   ./load-updates.sh --pull              # Pull latest tarballs from GHCR
#   ./load-updates.sh /path/to/tarballs   # Load from local tarballs dir
#   ./load-updates.sh --extensions        # Load only extension tarballs
#   ./load-updates.sh --all               # Load all tarballs (default)
#
# Tarball naming convention:
#   pi-<sha>.tar.gz        — Patched pi packages
#   lemonade-<sha>.tar.gz  — Lemonade plugin
#   memory-<sha>.tar.gz    — Memory extension  
#   config-<sha>.tar.gz    — Project config
#
# Sources (in order of precedence):
#   1. Local tarballs directory (/opt/pi-tarballs/)
#   2. GHCR: ghcr.io/localpibox/devstack-updates:<name>

set -euo pipefail

TARBALLS_DIR="/opt/pi-tarballs"
PI_SRC="/opt/pi-src"
PI_AGENTS="/home/dev/.pi/agent"

# Color codes
GREEN=$(printf '\033[0;32m')
YELLOW=$(printf '\033[1;33m')
RED=$(printf '\033[0;31m')
CYAN=$(printf '\033[0;36m')
BOLD=$(printf '\033[1m')
NC=$(printf '\033[0m')

MODE="all"
SOURCE="local"

# ── Parse args ──────────────────────────────────────────────────────────────

while [ $# -gt 0 ]; do
    case "$1" in
        --pull) SOURCE="ghcr"; shift ;;
        --extensions) MODE="extensions"; shift ;;
        --all) MODE="all"; shift ;;
        --patches) MODE="patches"; shift ;;
        --config) MODE="config"; shift ;;
        --help|-h)
            echo "Usage: $0 [--pull] [--extensions|--patches|--config|--all]"
            echo ""
            echo "Load update tarballs without rebuilding."
            echo ""
            echo "Options:"
            echo "  --pull         Pull tarballs from GHCR"
            echo "  --extensions   Load only extension tarballs"
            echo "  --patches      Load only patch tarballs"
            echo "  --config       Load only config tarballs"
            echo "  --all          Load everything (default)"
            exit 0 ;;
        *)
            if [ -d "$1" ]; then
                TARBALLS_DIR="$1"
                SOURCE="local"
            else
                echo "Unknown option: $1"
                exit 1
            fi
            shift ;;
    esac
done

print_section() {
    echo ""
    echo -e "${CYAN}${BOLD}=== $1 ===${NC}"
}

print_ok() { echo -e "  ${GREEN}✓${NC} $1"; }
print_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }

# ── Helper: check if tarball is newer ───────────────────────────────────────

is_newer() {
    local current="$1"
    local tarball="$2"
    local tarball_date
    tarball_date=$(date -d "$(zcat "$tarball" | tar --list | head -1 | cut -d: -f2)" +%s 2>/dev/null || echo 0)
    local current_date
    current_date=$(stat -c '%Y' "$current" 2>/dev/null || echo 0)
    [ "$tarball_date" -gt "$current_date" ] 2>/dev/null
}

# ── Load Pi patches ────────────────────────────────────────────────────────

load_pi_patches() {
    print_section "Pi Patches"
    
    if [ "$MODE" != "all" ] && [ "$MODE" != "patches" ]; then
        print_warn "Skipping (not in mode)"
        return 0
    fi
    
    # Find matching tarball
    local tarball
    tarball=$(ls -t "$TARBALLS_DIR"/pi-*.tar.gz 2>/dev/null | head -1)
    
    if [ -z "$tarball" ]; then
        if [ "$SOURCE" = "ghcr" ]; then
            print_warn "No local tarball found"
            return 0
        fi
    fi
    
    if [ -z "$tarball" ]; then
        print_warn "No pi tarball found"
        return 0
    fi
    
    echo -n "  Loading pi tarball... "
    # Extract and rebuild
    tar xzf "$tarball" -C "$PI_SRC" 2>/dev/null || { print_warn "extract failed"; return 0; }
    (cd "$PI_SRC" && npm run build 2>&1 | tail -1) 2>/dev/null || print_warn "build failed"
    print_ok "loaded $tarball"
    
    # Reinstall global packages
    if [ -f "$PI_SRC/package.json" ]; then
        echo -n "  Reinstalling global packages... "
        (cd "$PI_SRC" && npm install -g "./packages/ai" "./packages/agent" "./packages/coding-agent" "./packages/tui") 2>&1 | tail -1 | sed 's/^/    /'
        print_ok "global packages updated"
    fi
}

# ── Load extensions ────────────────────────────────────────────────────────

load_extensions() {
    print_section "Extensions"
    
    if [ "$MODE" != "all" ] && [ "$MODE" != "extensions" ]; then
        print_warn "Skipping (not in mode)"
        return 0
    fi
    
    # Use Pi's native update command — checks all configured packages and
    # installs/updates only those that differ from the latest release.
    # The old `pi list | grep → skip` pattern only checks existence, never triggers updates.
    echo -n "  Running pi update --extensions... "
    if pi update --extensions 2>&1; then
        print_ok "extensions updated"
    else
        print_warn "pi update --extensions reported errors (some extensions may need manual attention)"
    fi

    # Verify all expected extensions are present
    local extensions=(
        "git:github.com/localpibox/lemonade-pi-plugin@patches/api-key-auth"
        "git:github.com/localpibox/pi-hermes-memory@fix/subprocess-provider"
        "npm:pi-mcp-adapter"
        "npm:@tintinweb/pi-subagents"
        "npm:pi-powerline-footer"
    )
    for ext in "${extensions[@]}"; do
        local name=$(echo "$ext" | sed 's|.*:||' | sed 's|@.*||')
        echo -n "  Verifying $name... "
        if pi list --json 2>/dev/null | grep -q "$name" 2>/dev/null; then
            print_ok "installed"
        else
            print_warn "missing — run: pi install ${ext}"
        fi
    done
}

# ── Load config ─────────────────────────────────────────────────────────────

load_config() {
    print_section "Config"
    
    if [ "$MODE" != "all" ] && [ "$MODE" != "config" ]; then
        print_warn "Skipping (not in mode)"
        return 0
    fi
    
    local tarball
    tarball=$(ls -t "$TARBALLS_DIR"/config-*.tar.gz 2>/dev/null | head -1)
    
    if [ -z "$tarball" ]; then
        if [ "$SOURCE" = "ghcr" ]; then
            print_warn "No local config tarball found"
            return 0
        fi
    fi
    
    if [ -z "$tarball" ]; then
        print_warn "No config tarball found"
        return 0
    fi
    
    echo "  Extracting config tarball..."
    
    # Extract to temp location first
    local tmpdir=$(mktemp -d)
    tar xzf "$tarball" -C "$tmpdir"
    
    # Copy config files
    mkdir -p "$PI_AGENTS"
    for file in settings.json mcp.json AGENTS.md; do
        if [ -f "$tmpdir/$file" ]; then
            cp "$tmpdir/$file" "$PI_AGENTS/$file"
            echo "  ${GREEN}✓${NC} Copied $file"
        fi
    done
    
    # Copy skills
    if [ -d "$tmpdir/skills" ]; then
        for skill_dir in "$tmpdir/skills"/*/; do
            [ -d "$skill_dir" ] || continue
            local skill_name=$(basename "$skill_dir")
            mkdir -p "/home/dev/.pi/agent/skills/$skill_name"
            cp "$skill_dir"* "/home/dev/.pi/agent/skills/$skill_name/" 2>/dev/null || true
            echo "  ${GREEN}✓${NC} Copied skill: $skill_name"
        done
    fi
    
    # Copy agents
    if [ -d "$tmpdir/agents" ]; then
        cp "$tmpdir/agents"/* "/home/dev/.pi/agent/agents/" 2>/dev/null || true
        echo "  ${GREEN}✓${NC} Copied agents"
    fi
    
    # Cleanup
    rm -rf "$tmpdir"
    print_ok "config updated"
}

# ── Pull from GHCR ──────────────────────────────────────────────────────────

detect_container_cmd() {
    if command -v podman &>/dev/null; then
        echo podman
    elif command -v docker &>/dev/null; then
        echo docker
    else
        echo ""
    fi
}

pull_from_ghcr() {
    local IMAGE="ghcr.io/localpibox/devstack-updates"
    local CTR
    CTR=$(detect_container_cmd)

    if [ -z "$CTR" ]; then
        echo -e "${RED}ERROR: Neither podman nor docker found.${NC}"
        return 1
    fi

    echo -e "${CYAN}Pulling tarballs from GHCR using $CTR...${NC}"

    # Create tarballs directory if it doesn't exist
    mkdir -p "$TARBALLS_DIR"

    for name in pi lemonade memory config; do
        echo -n "  Pulling $name... "
        if $CTR pull "$IMAGE:$name" 2>/dev/null; then
            # Extract from image
            local container
            container=$($CTR create "$IMAGE:$name" 2>/dev/null)
            $CTR cp "$container:/$(basename "$name").tar.gz" "$TARBALLS_DIR/$name.tar.gz" 2>/dev/null || \
                print_warn "$name (extract failed)"
            $CTR rm "$container" 2>/dev/null || true
            print_ok "$name"
        else
            print_warn "$name (not found on GHCR)"
        fi
    done
}

# ── Main ────────────────────────────────────────────────────────────────────

echo -e "${BOLD}Loading updates${NC}"
echo "  Mode:  $MODE"
echo "  Source: $SOURCE"
echo "  Dir:   $TARBALLS_DIR"

# Pull if requested
if [ "$SOURCE" = "ghcr" ]; then
    pull_from_ghcr
fi

# Load based on mode
case "$MODE" in
    patches)    load_pi_patches ;;
    extensions) load_extensions ;;
    config)     load_config ;;
    all)
        load_pi_patches
        load_extensions
        load_config
        ;;
esac

echo ""
echo -e "${GREEN}${BOLD}Update complete.${NC}"
echo ""
echo "You may need to restart the editor for changes to take effect:"
echo "  docker exec -it localpibox systemctl restart vscodium-server"
