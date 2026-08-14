#!/usr/bin/env bash
# version.sh — Bump the devstack VERSION and update LPB_PI_REF
#
# Usage:
#   ./support/version.sh patch  — bump 0.0.26-lpb-dev → 0.0.27-lpb-dev
#   ./support/version.sh minor  — bump 0.0.26-lpb-dev → 0.1.0-lpb-dev
#   ./support/version.sh major  — bump 0.0.26-lpb-dev → 1.0.0-lpb-dev
#
# What it does:
#   1. Bumps the VERSION file in this repo
#   2. Updates LPB_PI_REF in lpb.stack.env
#   3. Updates package pins in settings.json (lemonade-pi-plugin, lpb-memory, pi-subagents)

set -euo pipefail
cd "$(dirname "$0")/.."

bump_type="${1:-}"
if [[ -z "$bump_type" || ! "$bump_type" =~ ^(patch|minor|major)$ ]]; then
    echo "Usage: $0 {patch|minor|major}" >&2
    exit 1
fi

# ─── Read current version ────────────────────────────────────────────────────
ver=$(cat VERSION 2>/dev/null || echo "0.0.0-lpb")
base=$(echo "$ver" | sed 's/^[0-9]*\.[0-9]*\.[0-9]*//')
major=$(echo "$ver" | sed 's/^\([0-9]*\)\..*/\1/')
minor=$(echo "$ver" | sed 's/^[0-9]*\.\([0-9]*\)\..*/\1/')
patch=$(echo "$ver" | sed 's/^[0-9]*\.[0-9]*\.\([0-9]*\).*/\1/')

case "$bump_type" in
    patch)  patch=$((patch + 1)); minor=0; major=$major ;;
    minor)  minor=$((minor + 1)); patch=0 ;;
    major)  major=$((major + 1)); minor=0; patch=0 ;;
esac
new_ver="${major}.${minor}.${patch}${base}"
echo "Bumping $ver → $new_ver"

# ─── 1. Update VERSION ──────────────────────────────────────────────────────
echo "$new_ver" > VERSION

# ─── 2. Update LPB_PI_REF ───────────────────────────────────────────────────
if [ -f "lpb.stack.env" ]; then
    sed -i "s/^LPB_PI_REF=.*/LPB_PI_REF=$new_ver/" lpb.stack.env
    echo "  lpb.stack.env: LPB_PI_REF=$new_ver"
fi

# ─── 3. Update settings.json package pins ───────────────────────────────────
settings="$HOME/.pi/agent/settings.json"
if [ -f "$settings" ]; then
    python3 -c "
import json, sys
with open('$settings') as f:
    d = json.load(f)
pins = {
    'lemonade-pi-plugin': 'git:github.com/localpibox/lemonade-pi-plugin@$new_ver',
    'lpb-memory': 'git:github.com/localpibox/lpb-memory@$new_ver',
    'pi-subagents': 'git:github.com/localpibox/pi-subagents@$new_ver',
}
for pkg in d.get('packages', []):
    for name in pins:
        if name in pkg:
            idx = d['packages'].index(pkg)
            d['packages'][idx] = pins[name]
            print(f'  settings.json: {pkg} -> {pins[name]}')
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
"
fi

echo "Done. Review and commit: git add VERSION lpb.stack.env ~/.pi/agent/settings.json"
