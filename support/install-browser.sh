#!/usr/bin/env bash
# install-browser.sh — Install Chrome + agent-browser (with system deps)
#
# This script replaces the pre-built Chrome + GTK/X11 lib bloat from the
# Dockerfile. It downloads Chrome-for-Testing and runs `agent-browser install
# --with-deps` which uses Playwright's dependency resolver to install only the
# exact libraries needed for the downloaded Chrome version.
#
# Usage:
#   Inside container (as root or with sudo):
#     bash /opt/devstack/install-browser.sh
#
# Outside container (development host):
#   bash /opt/devstack/install-browser.sh

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Detect if running inside container ──────────────────────────────────────
IS_CONTAINER=false
if [ -f /.dockerenv ] || grep -qs docker /proc/1/cgroup 2>/dev/null; then
    IS_CONTAINER=true
fi

# ── Step 1: Download Chrome-for-Testing ────────────────────────────────────
install_chrome() {
    info "Downloading latest Chrome for Testing..."

    local chrome_version
    chrome_version=$(curl -s https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json \
        | jq -r '.channels.Stable.version')

    if [ -z "$chrome_version" ] || [ "$chrome_version" = "null" ]; then
        error "Failed to fetch Chrome version"
        return 1
    fi

    info "Chrome version: $chrome_version"

    local chrome_dir="/home/dev/.agent-browser/browsers/chrome-${chrome_version}"
    local chrome_zip="/tmp/chrome-${chrome_version}.zip"

    if [ -d "$chrome_dir" ] && [ -f "${chrome_dir}/chrome-linux64/chrome" ]; then
        warn "Chrome already installed at $chrome_dir"
        rm -f "$chrome_zip"
        return 0
    fi

    mkdir -p "$chrome_dir"
    curl -L "https://storage.googleapis.com/chrome-for-testing-public/${chrome_version}/linux64/chrome-linux64.zip" \
        -o "$chrome_zip"

    unzip -q "$chrome_zip" -d "$chrome_dir"
    rm -f "$chrome_zip"

    # Verify
    if [ -f "${chrome_dir}/chrome-linux64/chrome" ]; then
        info "Chrome extracted to $chrome_dir"
    else
        error "Chrome extraction failed"
        return 1
    fi
}

# ── Step 2: Install agent-browser + system deps ────────────────────────────
install_agent_browser() {
    info "Installing agent-browser with system dependencies..."

    # agent-browser install --with-deps uses Playwright's nativeDeps resolver
    # to install exactly the right libraries for the Chrome version
    if agent-browser install; then
        info "agent-browser installed successfully"
    else
        error "agent-browser install failed"
        return 1
    fi

    if agent-browser install --with-deps; then
        info "agent-browser system dependencies installed"
    else
        warn "Some system dependencies may be missing; Chrome may fail at runtime"
    fi
}

# ── Step 3: Verify installation ───────────────────────────────────────────
verify_installation() {
    info "Verifying installation..."

    local errors=0

    # Check Chrome binary
    local chrome_paths=(
        "/home/dev/.agent-browser/browsers/chrome-*/chrome-linux64/chrome"
        "/opt/google/chrome/chrome"
    )
    local chrome_found=false
    for p in "${chrome_paths[@]}"; do
        if ls "$p" &>/dev/null; then
            info "  Chrome: $p"
            "$p" --version 2>/dev/null || true
            chrome_found=true
            break
        fi
    done
    $chrome_found || { error "  Chrome binary not found"; errors=$((errors + 1)); }

    # Check agent-browser binary
    if command -v agent-browser &>/dev/null; then
        info "  agent-browser: $(agent-browser --version 2>/dev/null || echo 'installed')"
    else
        error "  agent-browser binary not found"
        errors=$((errors + 1))
    fi

    if [ $errors -gt 0 ]; then
        error "$errors check(s) failed"
        return 1
    fi

    info "Browser setup complete!"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    info "Browser install script starting (container=$IS_CONTAINER)"

    install_chrome
    install_agent_browser
    verify_installation
}

main "$@"
