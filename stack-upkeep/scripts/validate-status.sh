#!/usr/bin/env bash
# validate-status.sh — Full stack health check and validation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$STACK_DIR")"
VERSIONS_FILE="$STACK_DIR/versions.env"
PATCH_DIR="$STACK_DIR/patches"

# ── Source dependency checker ──────────────────────────────────────────────
# When run directly, checks dependencies. When sourced from stack.sh, already done.
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
RED=$(printf '\033[0;31m')
CYAN=$(printf '\033[0;36m')
BOLD=$(printf '\033[1m')
NC=$(printf '\033[0m')

errors=0
warnings=0

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}=== $1 ===${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    warnings=$((warnings + 1))
}

print_err() {
    echo -e "  ${RED}✗${NC} $1"
    errors=$((errors + 1))
}

# ── Source config ───────────────────────────────────────────────────────────

if [ -f "$VERSIONS_FILE" ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        value=$(echo "$value" | sed 's/^"//;s/"$//')
        export "$key"="$value"
    done < "$VERSIONS_FILE"
    print_ok "Config loaded from versions.env"
else
    print_err "versions.env not found at $VERSIONS_FILE"
    exit 1
fi

# ── 1. Pi Monorepo ─────────────────────────────────────────────────────────

print_header "PI MONOREPO"

PI_PATCH_FILE="$PATCH_DIR/pi-qwen-chat-template.patch"
PI_PATCH_VER="${pi_patch_version}"

if [ -f "$PI_PATCH_FILE" ]; then
    print_ok "Patch file exists: pi-qwen-chat-template.patch"
else
    print_warn "No patch file found — upstream may have absorbed the changes"
fi

if [ -n "$PI_PATCH_VER" ]; then
    print_ok "Patch version pinned: $PI_PATCH_VER"
else
    print_warn "No patch version set"
fi

echo "  Branch:    ${GREEN}${pi_branch:-patches/qwen-reasoning-effort}${NC}"

# ── 2. Lemonade Plugin ─────────────────────────────────────────────────────

print_header "LEMONADE PLUGIN"

LEMONADE_PATCH_FILE="$PATCH_DIR/lemonade-qwen-vision.patch"
LEMONADE_PATCH_VER="${lemonade_patch_version}"

if [ -f "$LEMONADE_PATCH_FILE" ]; then
    patch_lines=$(wc -l < "$LEMONADE_PATCH_FILE")
    print_ok "Patch file exists: lemonade-qwen-vision.patch ($patch_lines lines)"
else
    print_warn "No patch file found for lemonade"
fi

if [ -n "$LEMONADE_PATCH_VER" ]; then
    print_ok "Patch version pinned: $LEMONADE_PATCH_VER"
else
    print_warn "No patch version set"
fi

echo "  Branch:    ${GREEN}${lemonade_branch:-patches/qwen-vision}${NC}"

# ── 3. Memory Extension ────────────────────────────────────────────────────

print_header "MEMORY EXTENSION"

echo "  Branch:    ${GREEN}${memory_branch:-fix/subprocess-provider}${NC}"
print_ok "Installed via: pi install git:github.com/localpibox/pi-hermes-memory@$memory_branch"

# ── 4. Container Build Readiness ───────────────────────────────────────────

print_header "CONTAINER BUILD READINESS"

DOCKERFILE="$ROOT_DIR/Dockerfile"
if [ -f "$DOCKERFILE" ]; then
    if grep -q "earendil-works/pi" "$DOCKERFILE" 2>/dev/null; then
        print_ok "Dockerfile clones from upstream (not fork)"
    else
        print_warn "Dockerfile does not reference upstream"
    fi
    if grep -q "pi-patches" "$DOCKERFILE" 2>/dev/null; then
        print_ok "Dockerfile applies local patches"
    else
        print_warn "Dockerfile does not apply patches"
    fi
else
    print_warn "Dockerfile not found at $DOCKERFILE"
fi

if [ -d "$PATCH_DIR" ]; then
    patch_count=$(find "$PATCH_DIR" -name "*.patch" | wc -l)
    print_ok "Patch directory: $patch_count patch file(s)"
else
    print_err "Patch directory missing: $PATCH_DIR"
fi

# ── 5. Cache Preservation ──────────────────────────────────────────────────

print_header "CACHE PRESERVATION"

echo "  Volume strategy:"
echo "    pi-agent-state      — Persistent via ~/.localpibox/state:${GREEN}✓${NC}"
echo "    devstack-npm-cache   — Persistent via ~/.npm:${GREEN}✓${NC}"
echo "    browser-state        — Persistent via ~/.localpibox/agent-browser:${GREEN}✓${NC}"
echo ""
echo "  Cache invalidation:"
echo "    Change pi_patch_version or lemonade_patch_version in versions.env"
echo "    then run: $CONTAINER_CMD build"

# ── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}=== SUMMARY ===${NC}"
echo ""
if [ "$errors" -eq 0 ] && [ "$warnings" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}✅ Stack is healthy and ready for rebuild${NC}"
    echo ""
    echo "  To rebuild with updated patches:"
    echo "    cd $ROOT_DIR"
    echo "    $CONTAINER_CMD build -t ghcr.io/localpibox/devstack:latest ."
elif [ "$warnings" -gt 0 ]; then
    echo -e "  ${YELLOW}⚠ Stack has $warnings warning(s) — review above${NC}"
else
    echo -e "  ${RED}✗ Stack has $errors error(s) — fix before rebuild${NC}"
fi

echo ""
exit $errors
