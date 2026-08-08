#!/usr/bin/env bash
# install-github-mcp-server.sh — Download and install the GitHub MCP Server
# pre-built binary into /home/lpb/.local/pi-support/bin/
#
# Usage:
#   ./install-github-mcp-server.sh        # latest release (default)
#   ./install-github-mcp-server.sh v1.8.0 # specific version
#
# The binary is consumed by the github-mcp-server MCP server entry in
# ~/.pi/agent/mcp.json (sourced from localpibox/config repo).

set -euo pipefail

VERSION="${1:-latest}"
BINARY_DIR="/home/lpb/.local/pi-support/bin"
REPO="github/github-mcp-server"

# Resolve version
if [ "$VERSION" = "latest" ]; then
  VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | jq -r '.tag_name')
  echo "Latest version: ${VERSION}"
fi

# Architecture detection
ARCH=$(dpkg --print-architecture)
case "$ARCH" in
  amd64)  OS_ARCH="Linux_x86_64" ;;
  arm64)  OS_ARCH="Linux_arm64" ;;
  *) echo "ERROR: Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

echo "Installing GitHub MCP Server ${VERSION} (${OS_ARCH})..."
mkdir -p "$BINARY_DIR"

# Direct GitHub CDN (github.com/.../releases/download/...) returns 404 from this
# network. Download the release asset via the authenticated gh API octet-stream
# endpoint (redirects to object storage). Match by filename substring — full-
# string `==` on asset .name intermittently fails in gh's gojq, so use `contains`.
# Release tarball names carry NO version (github-mcp-server_${OS_ARCH}.tar.gz).
# Match by the OS_ARCH substring only.
_asset_match="${OS_ARCH}"
_asset_id="$(gh api "repos/${REPO}/releases/tags/${VERSION}" --jq '.assets[] | select(.name | contains("'"$_asset_match"'")) | .id' 2>/dev/null | head -1)"
if [[ -z "$_asset_id" ]]; then
    echo "ERROR: Could not resolve release asset for ${VERSION}" >&2
    exit 1
fi

TMP_TARBALL="/tmp/github-mcp-server.tar.gz"
gh api -H "Accept: application/octet-stream" "repos/${REPO}/releases/assets/${_asset_id}" > "$TMP_TARBALL" 2>/dev/null || {
    echo "ERROR: Failed to download GitHub MCP Server binary" >&2
    exit 1
}
tar -xzf "$TMP_TARBALL" -C "$BINARY_DIR"
rm -f "$TMP_TARBALL"

chmod +x "${BINARY_DIR}/github-mcp-server"
echo "Installed: ${BINARY_DIR}/github-mcp-server"
