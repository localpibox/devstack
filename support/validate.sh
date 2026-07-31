#!/usr/bin/env bash
# validate.sh — Check that the container is properly configured
#
# Run inside the container to verify:
#   - NOPASSWD sudo is configured
#   - Build tools are available
#   - Native modules (better-sqlite3) compile and load
#   - VSCodium server is accessible
#   - Pi CLI is functional
#
# Usage: podman exec -it localpibox /opt/devstack/validate.sh

set -euo pipefail

RED=$(printf '\033[0;31m')
GREEN=$(printf '\033[0;32m')
YELLOW=$(printf '\033[1;33m')
NC=$(printf '\033[0m')

errors=0
checks=0

pass() { echo -e "  ${GREEN}✓${NC} $1"; checks=$((checks + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; checks=$((checks + 1)); errors=$((errors + 1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; checks=$((checks + 1)); }

echo -e "${GREEN}=== LocalPibox Devstack Validation ===${NC}"
echo ""

# ── 1. NOPASSWD sudo ────────────────────────────────────────────────────────
echo -e "${CYAN}── NOPASSWD sudo ──────────────────────────────────────────${NC}"
if [ -f /etc/sudoers.d/nopasswd ] && grep -q 'NOPASSWD:ALL' /etc/sudoers.d/nopasswd 2>/dev/null; then
    pass "NOPASSWD configured for dev user"
    if sudo echo works 2>/dev/null; then
        pass "sudo works without password prompt"
    else
        fail "sudo requires a password (NOPASSWD not working)"
    fi
else
    fail "NOPASSWD file missing at /etc/sudoers.d/nopasswd"
fi
echo ""

# ── 2. Build tools ──────────────────────────────────────────────────────────
echo -e "${CYAN}── Build tools ───────────────────────────────────────────${NC}"
for tool in gcc g++ make python3 pkg-config; do
    if command -v "$tool" &>/dev/null; then
        pass "$tool available"
    else
        fail "$tool missing"
    fi
done
if [ -f /usr/lib/x86_64-linux-gnu/libsqlite3.so ] || [ -f /usr/lib/x86_64-linux-gnu/libsqlite3.so.* ]; then
    pass "libsqlite3-dev (shared library) installed"
else
    fail "libsqlite3-dev (shared library) missing"
fi
echo ""

# ── 3. Native modules (better-sqlite3) ──────────────────────────────────────
echo -e "${CYAN}── Native modules ────────────────────────────────────────${NC}"
EXT_BASE="/home/dev/.pi/agent/git"
for ext_dir in "${EXT_BASE}"/*/*/node_modules/better-sqlite3; do
    [ -d "$ext_dir" ] || continue
    ext_name=$(basename "$(dirname "$ext_dir")")
    node_bin="$ext_dir/build/Release/better_sqlite3.node"
    
    if [ -f "$node_bin" ]; then
        pass "better-sqlite3 binary exists in $ext_name"
        
        # Test loading
        if cd "$ext_dir/.." && node -e "const db = require('better-sqlite3')(':memory:'); db.close()" 2>/dev/null; then
            pass "better-sqlite3 loads and queries in $ext_name"
        else
            fail "better-sqlite3 fails to load in $ext_name"
        fi
    else
        fail "better-sqlite3 binary missing in $ext_name (needs rebuild)"
        
        # Try rebuild if build tools are available
        if command -v gcc &>/dev/null && command -v make &>/dev/null; then
            echo -e "    ${YELLOW}Rebuilding...${NC}"
            (cd "$ext_dir" && npx node-gyp rebuild --release 2>&1 | tail -2) || true
            if [ -f "$node_bin" ]; then
                pass "Rebuild succeeded for $ext_name"
            else
                fail "Rebuild failed for $ext_name"
            fi
        else
            echo -e "    ${RED}Cannot rebuild — build tools missing${NC}"
        fi
    fi
done

if [ ! -f "${EXT_BASE}"/*/node_modules/better-sqlite3/build/Release/better_sqlite3.node ] 2>/dev/null; then
    warn "No better-sqlite3 extensions found (expected for non-memory extensions)"
fi
echo ""

# ── 4. VSCodium server ──────────────────────────────────────────────────────
# ED_PORT and CONNECTION_TOKEN are set by start.sh from LPB_* vars
# (backwards-compat aliases)
ED_PORT="${ED_PORT:-3000}"
CONNECTION_TOKEN="${CONNECTION_TOKEN:-devsession}"
echo -e "${CYAN}── VSCodium server ───────────────────────────────────────${NC}"
if curl -sf "http://localhost:${ED_PORT}/?tkn=${CONNECTION_TOKEN}" >/dev/null 2>&1; then
    pass "VSCodium server responsive on port $ED_PORT"
else
    fail "VSCodium server not responsive on port $ED_PORT"
fi
echo ""

# ── 5. Pi CLI ──────────────────────────────────────────────────────────────
echo -e "${CYAN}── Pi CLI ────────────────────────────────────────────────${NC}"
if command -v pi &>/dev/null; then
    pass "pi command available"
    pi --version 2>/dev/null && pass "pi --version works" || fail "pi --version failed"
else
    fail "pi command not found"
fi
echo ""

# ── 6. Extensions ───────────────────────────────────────────────────────────
echo -e "${CYAN}── Extensions ────────────────────────────────────────────${NC}"
for ext_repo in localpibox/lemonade-pi-plugin localpibox/pi-hermes-memory; do
    ext_path=$(find "${EXT_BASE}" -path "*${ext_repo}*" -name "package.json" 2>/dev/null | head -1)
    if [ -n "$ext_path" ]; then
        ext_name=$(basename "$(dirname "$ext_path")")
        pass "$ext_name installed"
    else
        fail "$ext_repo not found in ${EXT_BASE}"
    fi
done
echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo -e "${GREEN}=== Summary ===${NC}"
echo -e "  Checks:  $checks"
echo -e "  Errors:  $errors"
echo ""
if [ "$errors" -eq 0 ]; then
    echo -e "  ${GREEN}✅ All checks passed — devstack is healthy${NC}"
else
    echo -e "  ${RED}✗ $errors check(s) failed — review above${NC}"
fi

exit $errors
