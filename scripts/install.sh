#!/usr/bin/env bash
# Installer for lpb (LocalPibox Devstack launcher)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/localpibox/devstack/main/scripts/install.sh | bash
#
# Best practice: download first, inspect, then run
#   curl -fsSL https://raw.githubusercontent.com/localpibox/devstack/main/scripts/install.sh -o /tmp/install.sh
#   cat /tmp/install.sh
#   bash /tmp/install.sh

set -euo pipefail

INSTALL_DIR="${HOME}/.local/bin"
CONFIG_DIR="${HOME}/.localpibox/devstack"
CONFIG_FILE="${CONFIG_DIR}/config"
SCRIPT_URL="https://raw.githubusercontent.com/localpibox/devstack/main/scripts/lpb"

# 1. Validate prerequisites
for dep in curl; do
    command -v "$dep" >/dev/null 2>&1 || { echo "ERROR: $dep is required"; exit 1; }
done
command -v podman 2>/dev/null || command -v docker 2>/dev/null || \
    { echo "WARNING: Neither podman nor docker found — lpb will need one to run"; }

# 2. Create directories
mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}"

# 3. Download and install script
echo "Installing lpb..."
curl -fsSL "${SCRIPT_URL}" -o "${INSTALL_DIR}/lpb"
chmod +x "${INSTALL_DIR}/lpb"

# 4. Add to PATH if needed (warn only, don't modify shell configs)
case ":${PATH}:" in
    *:"${INSTALL_DIR}":*)
        echo "  ${INSTALL_DIR} is already in PATH" ;;
    *)
        echo "  ${INSTALL_DIR} is NOT in PATH — add it:"
        echo "    export PATH=\"${INSTALL_DIR}:\${PATH}\""
        echo "  Or add to ~/.bashrc / ~/.zshrc" ;;
esac

# 5. Create default config
if [ ! -f "${CONFIG_FILE}" ]; then
    cat > "${CONFIG_FILE}" <<'EOF'
# ─── Devstack global config ───────────────────────────────────────────────
# Edit this file to override defaults. Values are in the form:
#   export VAR_NAME="value"
#
# Project-specific overrides go in:
#   ~/.localpibox/devstack/projects/<project-name>

# ─── Container ──────────────────────────────────────────────────────────────
export LPB_IMAGE_NAME="ghcr.io/localpibox/devstack:latest"
export LPB_CONTAINER_NAME="localpibox"

# ─── VSCodium ───────────────────────────────────────────────────────────────
export LPB_PORT=8000
export LPB_EDITOR_HOST="localhost"
# Connection token — leave empty to auto-generate per session (recommended).
export LPB_CONNECTION_TOKEN=""

# ─── VSCodium advanced ─────────────────────────────────────────────────────
export LPB_DATA_DIR="${HOME}/.localpibox/devstack/server-data"
export LPB_USER_DATA_DIR="${HOME}/.localpibox/devstack/user-data"
export LPB_EXT_DIR="${HOME}/.vscodium-server/extensions"
export LPB_BASE_PATH="/"

# ─── Directories ────────────────────────────────────────────────────────────
export LPB_STATE_DIR="${HOME}/.localpibox/state"
export LPB_BROWSER_DIR="${HOME}/.localpibox/agent-browser"
EOF
    echo "  Created config: ${CONFIG_FILE}"
fi

echo ""
echo "✓ lpb installed to ${INSTALL_DIR}/lpb"
echo ""
echo "Usage examples:"
echo "  lpb                              — Start VSCodium at ~ (pick project)"
echo "  lpb /path/to/project              — Start VSCodium at project"
echo "  lpb /path/to/project --port 8080  — Custom port"
echo "  lpb --without-token               — No auth (localhost only!)"
echo "  lpb --stop                        — Stop container"
echo "  lpb --logs                        — View logs"
echo "  lpb --remove                      — Remove everything"
echo ""
echo "Config: ${CONFIG_FILE}"
echo "Docs:   lpb --help"
