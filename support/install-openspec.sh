#!/usr/bin/env bash
# install-openspec.sh — Install OpenSpec in the current workspace (opt-in)
#
# This script bootstraps OpenSpec spec-driven development in the current
# project. It installs the CLI (if missing), runs `openspec init` with
# sensible defaults for Pi, and verifies the result.
#
# Usage:
#   Inside container (from any workspace directory):
#     bash /opt/pi-support/bin/install-openspec.sh
#
#   From the workspace root explicitly:
#     bash /opt/pi-support/bin/install-openspec.sh /path/to/project
#
# What it does:
#   1. Installs the OpenSpec CLI globally (idempotent, 3 retries)
#   2. Ensures global config is set (delivery: both, profile: core)
#   3. Runs `openspec init --tools pi` in the target directory
#   4. Verifies generated files are present and loadable by Pi
#
# Generated structure:
#   openspec/              ← specs, changes, config.yaml (version-controlled)
#   .pi/prompts/           ← /opsx:propose, /opsx:apply, etc.
#   .pi/skills/openspec-*/ ← skill definitions
#
# Sensitive files (.gitignore patterns):
#   .pi/prompts/   (generated, don't commit)
#   .pi/skills/    (generated, don't commit)

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Config ──────────────────────────────────────────────────────────────────
OPENSPEC_PKG="@fission-ai/openspec"
OPENSPEC_CMD="openspec"
OPENSPEC_VERSION="latest"

# ── Resolve target directory ───────────────────────────────────────────────
TARGET_DIR="${1:-.}"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

# ── Install OpenSpec CLI (idempotent, 3 retries) ───────────────────────────
install_openspec() {
    if command -v "$OPENSPEC_CMD" &>/dev/null; then
        local version
        version=$("$OPENSPEC_CMD" --version 2>/dev/null || echo "installed")
        info "OpenSpec $version already installed, skipping"
        return 0
    fi

    info "Installing $OPENSPEC_PKG@$OPENSPEC_VERSION ..."

    # Ensure npm uses ~/.npm-global (the Dockerfile sets this at build time
    # but the .npmrc gets overwritten — so we must re-set it at runtime).
    npm config set prefix "$HOME/.npm-global" 2>/dev/null || true

    local attempt
    for attempt in 1 2 3; do
        if npm install -g "$OPENSPEC_PKG@$OPENSPEC_VERSION" 2>&1; then
            if command -v "$OPENSPEC_CMD" &>/dev/null; then
                info "OpenSpec installed successfully"
                return 0
            fi
        fi
        if [ "$attempt" -lt 3 ]; then
            warn "Attempt $attempt failed, retrying in 5s..."
            sleep 5
        fi
    done

    error "Failed to install OpenSpec after 3 attempts"
    return 1
}

# ── Configure OpenSpec global defaults ─────────────────────────────────────
# The defaults are delivery: both, profile: core — exactly what we want.
# No config change needed.
configure_openspec() {
    info "OpenSpec defaults: delivery=both, profile=core (already set)"
}

# ── Initialize OpenSpec in target directory ────────────────────────────────
init_openspec() {
    # Check if already initialized
    if [ -d "$TARGET_DIR/openspec" ]; then
        warn "openspec/ already exists in $TARGET_DIR"
        info "Running openspec update instead..."
        pushd "$TARGET_DIR" > /dev/null
        if "$OPENSPEC_CMD" update 2>&1; then
            info "OpenSpec updated successfully"
        else
            error "openspec update failed"
            popd > /dev/null
            return 1
        fi
        popd > /dev/null
        return 0
    fi

    info "Initializing OpenSpec in $TARGET_DIR ..."
    pushd "$TARGET_DIR" > /dev/null

    if ! "$OPENSPEC_CMD" init --tools pi 2>&1; then
        error "openspec init failed"
        popd > /dev/null
        return 1
    fi

    popd > /dev/null
    info "OpenSpec initialized successfully"
}

# ── Verify installation ────────────────────────────────────────────────────
verify_installation() {
    local errors=0

    info "Verifying installation..."

    # Check openspec/ directory
    if [ -d "$TARGET_DIR/openspec" ]; then
        info "  openspec/       ✓ specs + changes"
    else
        error "  openspec/       ✗ missing"
        errors=$((errors + 1))
    fi

    # Check config.yaml
    if [ -f "$TARGET_DIR/openspec/config.yaml" ]; then
        info "  config.yaml     ✓ project config"
    else
        warn "  config.yaml     — not found (optional)"
    fi

    # Check Pi prompts
    if [ -d "$TARGET_DIR/.pi/prompts" ]; then
        local count
        count=$(find "$TARGET_DIR/.pi/prompts" -name "opsx-*.md" 2>/dev/null | wc -l)
        info "  .pi/prompts/    ✓ $count command files"
    else
        warn "  .pi/prompts/    — not found (Pi may not see commands)"
    fi

    # Check Pi skills
    if [ -d "$TARGET_DIR/.pi/skills" ]; then
        local count
        count=$(find "$TARGET_DIR/.pi/skills" -maxdepth 1 -type d 2>/dev/null | wc -l)
        info "  .pi/skills/     ✓ $count skill directories"
    else
        warn "  .pi/skills/     — not found (Pi may not see skills)"
    fi

    # Check that prompts are loadable by Pi
    if [ -d "$TARGET_DIR/.pi/prompts" ]; then
        local has_propose=false
        if ls "$TARGET_DIR/.pi/prompts/opsx-propose.md" &>/dev/null || \
           ls "$TARGET_DIR/.pi/prompts/openspec-proposal.md" &>/dev/null; then
            has_propose=true
        fi
        if $has_propose; then
            info "  Pi discovery    ✓ commands will be available"
        else
            warn "  Pi discovery    — propose command not found"
        fi
    fi

    if [ $errors -gt 0 ]; then
        error "$errors check(s) failed"
        return 1
    fi

    info "OpenSpec setup complete!"
    info ""
    info "Next steps:"
    info "  cd $TARGET_DIR"
    info "  /opsx:explore          ← Think through an idea"
    info "  /opsx:propose \"name\"   ← Create a change plan"
    info "  /opsx:apply            ← Implement from tasks.md"
    info "  /opsx:archive          ← Merge specs, file away"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    info "OpenSpec install script starting"
    info "Target: $TARGET_DIR"

    # Fix ~/.config ownership — OpenSpec writes ~/.config/openspec/ and crashes
    # with EACCES if the dir is owned by root (container issue).
    if [ -d "$HOME/.config" ] && [ "$(stat -c '%U' "$HOME/.config" 2>/dev/null)" != "$(whoami)" ]; then
        info "Fixing ~/.config ownership for OpenSpec..."
        sudo chown "$(whoami)" "$HOME/.config" 2>/dev/null || true
    fi

    install_openspec
    configure_openspec
    init_openspec
    verify_installation
}

main "$@"
