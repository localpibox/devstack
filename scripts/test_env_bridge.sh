#!/usr/bin/env bash
# test_env_bridge.sh — Generic LPB_ → bare-name bridge tests.
#
# Tests the MECHANISM, not individual variable names.
# The single source of truth is the BARE_NAMES array in start.sh.
#
# Validates:
#   1. Bridge function: LPB_ → bare-name with correct priority
#   2. BARE_NAMES array: syntax, completeness (mcp.json coverage)
#   3. persist_devstack_env() uses BARE_NAMES (not hardcoded string)
#   4. No hardcoded API keys in .env.example files
#   5. mcp.json env vars use ${VAR} references (structural)
#   6. .env.example files document the bridge
#   7. Full priority chain: shell > .env(LPB_) > conf > hardcoded

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVSTACK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$HOME/.pi/agent"
SUPPORT_SCRIPT="$DEVSTACK_DIR/support/start.sh"

PASS=0
FAIL=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

# ─── Source start.sh bridge logic in a clean subshell ────────────────────────
_source_bridge() {
    local bare_names_block bridge_block lib_func load_env_func
    bare_names_block=$(sed -n '/^BARE_NAMES=(/,/^)$/p' "$SUPPORT_SCRIPT")
    bridge_block=$(sed -n '/^_bridge() {/,/^}/p' "$SUPPORT_SCRIPT")
    lib_func=$(sed -n '/^parse_env_file() {/,/^}/p' "$DEVSTACK_DIR/support/_lib.sh")
    load_env_func='
_load_env_into_vars() {
        local file="$1"
        while IFS= read -r line; do
            [[ "$line" =~ ^LPB_ ]] || continue
            [[ -z "$line" ]] && continue
            local key="${line%%=*}" val="${line#*=}"
            val="${val#\"}"; val="${val%\"}"
            export "$key=$val"
        done < "$file"
    }
'

    bash -c "
        $lib_func
        $load_env_func
        $bare_names_block
        $bridge_block
        $1
    "
}

# Bridge-only: like _source_bridge but skips the BARE_NAMES export step.
# Used for priority tests where we control the initial LPB_ state.
_bridge_only() {
    local bridge_block lib_func
    bridge_block=$(sed -n '/^_bridge() {/,/^}/p' "$SUPPORT_SCRIPT")
    lib_func=$(sed -n '/^parse_env_file() {/,/^}/p' "$DEVSTACK_DIR/support/_lib.sh")
    local load_env_func='
_load_env_into_vars() {
        local file="$1"
        while IFS= read -r line; do
            [[ "$line" =~ ^LPB_ ]] || continue
            [[ -z "$line" ]] && continue
            local key="${line%%=*}" val="${line#*=}"
            val="${val#\"}"; val="${val%\"}"
            export "$key=$val"
        done < "$file"
    }
'
    local bare_inline='BARE_NAMES=(EXA_API_KEY CONTEXT7_API_KEY LEMONADE_BASE_URL OPENROUTER_BASE_URL ED_PORT HOST CONNECTION_TOKEN DEVCONTAINER_WORKSPACE_DIR MAX_TOKENS_CONTEXT_RATIO)'
    bash -c "
        $lib_func
        $load_env_func
        $bare_inline
        $bridge_block
        $1
    "
}

# ─── 1. Bridge Mechanism ─────────────────────────────────────────────────────

echo "=== 1. LPB_ → Bare Name Bridge Mechanism ==="

# 1a. Generic test: pick EXA_API_KEY, set LPB_FOO, verify FOO
r=$(_source_bridge '
    export "LPB_EXA_API_KEY=gen-test-value"
    _bridge
    echo "${EXA_API_KEY:-UNSET}"
')
[[ "$r" == "gen-test-value" ]] && pass "Generic: LPB_ bridges to bare" || fail "Generic: LPB_ bridge, got '$r'"

# 1b. Shell env priority: set bare + LPB_, verify bare wins
r=$(_source_bridge '
    export "CONTEXT7_API_KEY=shell-wins"
    export "LPB_CONTEXT7_API_KEY=lpb-loses"
    _bridge
    echo "${CONTEXT7_API_KEY}"
')
[[ "$r" == "shell-wins" ]] && pass "Generic: shell env > LPB_" || fail "Generic: shell priority, got '$r'"

# 1c. LPB_ value used when bare not set
r=$(_source_bridge '
    export "LPB_EXA_API_KEY=lpb-solo"
    _bridge
    echo "${EXA_API_KEY:-UNSET}"
')
[[ "$r" == "lpb-solo" ]] && pass "Generic: LPB_ fills when bare unset" || fail "Generic: LPB_ fill, got '$r'"

# ─── 2. BARE_NAMES Array ────────────────────────────────────────────────────

echo ""
echo "=== 2. BARE_NAMES Array ==="

count=$(grep -c '^    [A-Z_][A-Z_0-9]*$' "$SUPPORT_SCRIPT" | head -1)
if [[ "$count" -gt 0 ]]; then
    pass "BARE_NAMES: $count entries defined"
else
    fail "BARE_NAMES: no entries found"
fi

# All API key names in mcp.json should be in BARE_NAMES
mcp_json="$AGENT_DIR/mcp.json"
if [[ -f "$mcp_json" ]]; then
    all_covered=true
    for var in $(grep -oP '"[A-Z_]+_API_KEY"' "$mcp_json" | tr -d '"'); do
        if ! grep -q "^    ${var}$" "$SUPPORT_SCRIPT"; then
            all_covered=false
            break
        fi
    done
    $all_covered && pass "All mcp.json API keys in BARE_NAMES" || fail "Some mcp.json keys missing from BARE_NAMES"
fi

# ─── 3. persist_devstack_env Integration ─────────────────────────────────────

echo ""
echo "=== 3. persist_devstack_env Integration ==="

grep -q '${BARE_NAMES\[@\]}' "$SUPPORT_SCRIPT" && pass "Uses BARE_NAMES array (not hardcoded string)" || fail "Uses hardcoded bare_names"
grep -q '_bridge' "$SUPPORT_SCRIPT" && grep -c '_bridge' "$SUPPORT_SCRIPT" | grep -q '[2-9]' && pass "_bridge called multiple times (initial + after .env)" || fail "_bridge not called enough times"

# ─── 4. No Hardcoded Secrets in .env.example ─────────────────────────────────

echo ""
echo "=== 4. No Hardcoded Secrets ==="

for f in "$DEVSTACK_DIR/.env.example" "$AGENT_DIR/.env.example"; do
    [[ -f "$f" ]] || continue
    fname=$(basename "$f")
    has_key=false
    while IFS= read -r line; do
        [[ "$line" =~ ^# ]] && continue
        [[ -z "$line" ]] && continue
        val=$(echo "$line" | cut -d= -f2-)
        [[ -z "$val" ]] && continue
        [[ "$val" =~ ^(your-|change-|placeholder|REPLACE|sk-|ghp_|abc123) ]] && continue
        [[ ${#val} -gt 10 ]] && has_key=true && break
    done < <(grep -E '(EXA|CONTEXT7|GITHUB|OPENROUTER).*_API_KEY=|^.*_TOKEN=' "$f")
    $has_key && fail "Possible hardcoded secret in $fname" || pass "No hardcoded secrets in $fname"
done

# ─── 5. mcp.json Env Var Syntax (Structural) ─────────────────────────────────

echo ""
echo "=== 5. mcp.json Env Var Syntax ==="

if [[ -f "$mcp_json" ]]; then
    bad_refs=0
    while IFS= read -r val; do
        [[ -z "$val" ]] && continue
        [[ "$val" =~ ^\$\{ ]] && continue
        [[ ${#val} -gt 2 ]] && bad_refs=$((bad_refs + 1))
    done < <(grep -oP '"env"\s*:\s*\{[^}]*\}' "$mcp_json" | grep -oP '"[A-Z_]+_?\w*"\s*:\s*"(.*?)"' | cut -d'"' -f4)
    [[ "$bad_refs" -eq 0 ]] && pass "All mcp.json env values use \${VAR} references" || fail "$bad_refs non-reference values"
else
    pass "mcp.json not found — skipping"
fi

# ─── 6. .env.example Consistency ─────────────────────────────────────────────

echo ""
echo "=== 6. Consistency ==="

for f in "$DEVSTACK_DIR/.env.example" "$AGENT_DIR/.env.example"; do
    [[ -f "$f" && -s "$f" ]] && pass ".env.example exists: $(basename "$f")" || fail ".env.example missing/empty: $(basename "$f")"
done
grep -qi 'LPB_.*bridge\|LPB_.*bare\|LPB_.*prefix' "$AGENT_DIR/.env.example" 2>/dev/null && pass "Agent docs: LPB_→bare bridge documented" || fail "Agent docs: missing bridge note"
grep -q 'LPB_' "$DEVSTACK_DIR/.env.example" && pass "Devstack: uses LPB_ prefix" || fail "Devstack: missing LPB_ prefix"

# ─── 7. Full Priority Chain (End-to-End) ─────────────────────────────────────

echo ""
echo "=== 7. Full Priority Chain ==="

# 7a. Priority: shell env > .env(LP B_) > conf defaults
r=$(_bridge_only '
    echo "LPB_EXA_API_KEY=conf-default" > /tmp/test_conf.env
    _load_env_into_vars /tmp/test_conf.env
    export EXA_API_KEY=shell-key
    echo "LPB_EXA_API_KEY=env-key" > /tmp/test_env.env
    _load_env_into_vars /tmp/test_env.env
    _bridge
    echo "${EXA_API_KEY:-UNSET}"
')
[[ "$r" == "shell-key" ]] && pass "7a: shell > .env > conf" || fail "7a: expected shell-key, got $r"

# 7b. Priority: .env(LP B_) > conf defaults (no shell env)
r=$(_bridge_only '
    echo "LPB_EXA_API_KEY=conf-default" > /tmp/test_conf.env
    _load_env_into_vars /tmp/test_conf.env
    echo "LPB_EXA_API_KEY=env-key" > /tmp/test_env.env
    _load_env_into_vars /tmp/test_env.env
    _bridge
    echo "${EXA_API_KEY:-UNSET}"
')
[[ "$r" == "env-key" ]] && pass "7b: .env(LP B_) > conf default" || fail "7b: expected env-key, got $r"

# 7c. Priority: conf defaults > nothing
r=$(_bridge_only '
    echo "LPB_EXA_API_KEY=conf-default" > /tmp/test_conf.env
    _load_env_into_vars /tmp/test_conf.env
    _bridge
    echo "${EXA_API_KEY:-UNSET}"
')
[[ "$r" == "conf-default" ]] && pass "7c: conf default used when nothing else" || fail "7c: expected conf-default, got $r"

# 7d. Multiple LPB_ vars bridged (EXA + CONTEXT7 are the clean ones without special defaults)
r=$(_bridge_only '
    export "LPB_EXA_API_KEY=exa1"
    export "LPB_CONTEXT7_API_KEY=c71"
    _bridge
    echo "${EXA_API_KEY}:${CONTEXT7_API_KEY}"
')
[[ "$r" == "exa1:c71" ]] && pass "7d: multiple LPB_ vars bridged" || fail "7d: expected exa1:c71, got $r"

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
echo "========================================"

exit $FAIL
