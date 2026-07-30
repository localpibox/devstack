#!/usr/bin/env bash
# apply-patches.sh — Apply patch files to a repo cloned from upstream
#
# Usage: ./stack-upkeep/scripts/apply-patches.sh <repo-dir> [patch-dir]
#
# This is called during Docker build to apply local patches to an upstream
# clone. It reads versions.env to determine which patches to apply.
#
# Exit codes:
#   0  — All patches applied successfully
#   1  — Patch failed (needs manual intervention)
#   2  — No patches directory found (skip — repo may already have patches)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

REPO_DIR="${1:?Usage: $0 <repo-dir> [patch-dir]}"
PATCH_DIR="${2:-$ROOT_DIR/patches}"

echo "[apply-patches] Applying patches to: $REPO_DIR"
echo "[apply-patches] Patch directory: $PATCH_DIR"

# Check if patches directory exists
if [ ! -d "$PATCH_DIR" ]; then
    echo "[apply-patches] No patches directory found — skipping"
    exit 2
fi

# Check if there are any patch files
patch_count=$(find "$PATCH_DIR" -name "*.patch" -type f | wc -l)
if [ "$patch_count" -eq 0 ]; then
    echo "[apply-patches] No .patch files found — skipping"
    exit 2
fi

echo "[apply-patches] Found $patch_count patch file(s)"

# Apply patches in order
errors=0
for patch_file in "$PATCH_DIR"/*.patch; do
    patch_name=$(basename "$patch_file" .patch)
    echo ""
    echo "[apply-patches] Applying: $patch_name..."
    
    # Try to apply - if conflicts, abort and report
    if cd "$REPO_DIR" && git am "$patch_file" 2>&1; then
        echo "[apply-patches] ✓ $patch_name applied"
    else
        echo "[apply-patches] ✗ $patch_name FAILED — conflict detected"
        echo "[apply-patches]   The upstream has likely changed the patched file."
        echo "[apply-patches]   Resolve conflicts, commit, then update the patch."
        errors=$((errors + 1))
    fi
done

echo ""
if [ "$errors" -gt 0 ]; then
    echo "[apply-patches] ❌ $errors patch(es) failed"
    exit 1
else
    echo "[apply-patches] ✅ All $patch_count patch(es) applied"
    exit 0
fi
