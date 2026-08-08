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

TARBALL="github-mcp-server_${VERSION#v}_${OS_ARCH}.tar.gz"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${TARBALL}"

echo "Installing GitHub MCP Server ${VERSION} (${OS_ARCH})..."
mkdir -p "$BINARY_DIR"

curl -fsSL "$DOWNLOAD_URL" -o "/tmp/${TARBALL}"
tar -xzf "/tmp/${TARBALL}" -C "$BINARY_DIR"
rm -f "/tmp/${TARBALL}"

chmod +x "${BINARY_DIR}/github-mcp-server"
echo "Installed: ${BINARY_DIR}/github-mcp-server"
