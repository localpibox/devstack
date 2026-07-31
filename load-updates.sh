#!/usr/bin/env bash
# load-updates.sh — Load update tarballs into running container
#
# Usage:
#   ./load-updates.sh /path/to/tarballs/    # Load all tarballs
#   ./load-updates.sh /path/to/tarballs/ --push  # Load and verify

set -euo pipefail

TARBALLS_DIR="${1:?Usage: $0 <tarballs-dir>}"

if [ ! -d "$TARBALLS_DIR" ]; then
    echo "Error: tarballs directory not found: $TARBALLS_DIR"
    exit 1
fi

echo "Loading updates from $TARBALLS_DIR..."

for tarball in "$TARBALLS_DIR"/*.tar.gz; do
    [ -f "$tarball" ] || continue
    
    local name
    name=$(basename "$tarball" .tar.gz)
    echo "Loading $name..."
    
    # Extract to appropriate location
    case "$name" in
        pi-*)
            echo "  Extracting to /opt/pi-src/ (apply patches)"
            # Unpack and apply
            tar xzf "$tarball" -C /opt/pi-src 2>/dev/null || true
            ;;
        lemonade-*)
            echo "  Installing extension..."
            pi install "git:github.com/localpibox/lemonade-pi-plugin@patches/qwen-vision" 2>&1 | tail -1
            ;;
        memory-*)
            echo "  Installing extension..."
            pi install "git:github.com/localpibox/pi-hermes-memory@fix/subprocess-provider" 2>&1 | tail -1
            ;;
        config-*)
            echo "  Extracting config..."
            tar xzf "$tarball" -C /home/dev/.local/pi-config 2>/dev/null || true
            # Copy config files
            [ -f /home/dev/.local/pi-config/settings.json ] && \
                cp /home/dev/.local/pi-config/settings.json /home/dev/.pi/agent/settings.json
            [ -f /home/dev/.local/pi-config/mcp.json ] && \
                cp /home/dev/.local/pi-config/mcp.json /home/dev/.pi/agent/mcp.json
            ;;
    esac
    
    echo "  ✓ $name loaded"
done

echo ""
echo "All updates loaded."
