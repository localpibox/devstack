#!/usr/bin/env bash
# /opt/devstack/start.sh — Bootstrap + Start PI Agent + VSCodium.
# This script is the container's CMD entry point.

set -euo pipefail

# --- Configuration --------------------------------------------------------
WORKSPACE_DIR="${DEVCONTAINER_WORKSPACE_DIR:-/home/dev/workspace}"
HOME_DIR=/home/dev
LEMONADE_BASE_URL="${LEMONADE_BASE_URL:-http://127.0.0.1:13305/v1}"
PI_SUPPORT_DIR="${PI_SUPPORT_DIR:-/opt/pi-support}"

# --- Detect first run -----------------------------------------------------
FIRST_RUN=false
if [ ! -f "${HOME_DIR}/.pi/.initialized" ]; then
  FIRST_RUN=true
  echo "[devstack] First run detected — bootstrapping..."
fi

# --- Bootstrap (first run only) -------------------------------------------
if [ "$FIRST_RUN" = "true" ]; then

  # Fix volume ownership (Podman rootless may create as root)
  echo "[devstack] Fixing volume ownership..."
  sudo chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true
  sudo chmod -R u+rwX "${HOME_DIR}/.pi" "${HOME_DIR}/.npm" 2>/dev/null || true
  sudo chown -R "$(id -u):$(id -g)" "${HOME_DIR}/.config/codium" 2>/dev/null || true

  # Create required directories
  mkdir -p "${HOME_DIR}/.pi/agent/mcp" "${HOME_DIR}/.pi/agent/skills" "${HOME_DIR}/.venvs"

  # NPM config
  npm config set prefix '/home/dev/.npm-global'
  mkdir -p /home/dev/.npm-global/bin /home/dev/.npm-global/lib/node_modules
  # Fix ownership of .npm-global (root-owned files from Dockerfile npm install)
  sudo chown -R "$(id -u):$(id -g)" /home/dev/.npm-global 2>/dev/null || true
  npm config set fetch-retries 5
  npm config set fetch-retry-mintimeout 20000
  npm config set fetch-retry-maxtimeout 600000
  npm config set progress false
  npm config set allow-git all
  npm config set allow-scripts true

  # Helper: install global npm package (idempotent, 3 retries)
  npm_install_global() {
    local pkg="$1"
    npm config set prefix '/home/dev/.npm-global'
    if npm ls -g --prefix '/home/dev/.npm-global' "$pkg" >/dev/null 2>&1; then
      echo "[devstack] $pkg already installed, skipping"
      return 0
    fi
    for attempt in 1 2 3; do
      if npm install -g --prefix '/home/dev/.npm-global' "$pkg" 2>&1; then
        return 0
      fi
      echo "[devstack] npm install for $pkg failed on attempt $attempt; retrying..."
      sleep 5
    done
    echo "[devstack] ERROR: npm install for $pkg failed after 3 attempts"
    return 1
  }

  # Helper: install Pi extension (idempotent, 4 retries)
  pi_install() {
    local pkg="$1"
    if "pi" list --json 2>/dev/null | grep -q "$pkg"; then
      echo "[devstack] $pkg already installed, skipping"
      return 0
    fi
    if [[ "$pkg" != *":"* ]] && [[ "$pkg" != git+* ]]; then
      pkg="npm:${pkg}"
    fi
    for attempt in 1 2 3 4; do
      if "pi" install "$pkg" 2>&1; then
        return 0
      fi
      echo "[devstack] pi install ${pkg} failed on attempt ${attempt}; retrying..."
      sleep 10
    done
    echo "[devstack] ERROR: pi install ${pkg} failed after 4 attempts"
    return 1
  }

  # Install core tools
  echo "[devstack] Installing core tools..."
  npm_install_global @earendil-works/pi-coding-agent
  npm_install_global exa-mcp-server
  npm_install_global agent-browser
  pi_install npm:pi-hermes-memory
  pi_install npm:pi-mcp-adapter
  pi_install git:github.com/localpibox/lemonade-pi-plugin@main

  # Rebuild native modules
  echo "[devstack] Rebuilding native modules..."
  PI_NPM="${HOME_DIR}/.pi/agent/npm"
  BETTER_SQLITE3="$PI_NPM/node_modules/better-sqlite3"
  if [ -d "$BETTER_SQLITE3" ]; then
    (cd "$BETTER_SQLITE3" && npm run build-release 2>&1) \
      && echo "    better-sqlite3 rebuilt OK" \
      || echo "    [WARN] better-sqlite3 rebuild failed"
  else
    echo "    [WARN] better-sqlite3 not found"
  fi

  # Python venv
  echo "[devstack] Setting up Python venv..."
  python3 -m venv "${HOME_DIR}/.venvs/devstack" 2>/dev/null || true
  source "${HOME_DIR}/.venvs/devstack/bin/activate"
  pip install --upgrade pip 2>/dev/null || true

  # --- Copy shared skills from image to volume (first run only) -----------
  echo "[devstack] Installing skills..."
  SHARED_SKILLS_VOLUME="${HOME_DIR}/.pi/agent/skills"
  if [ -d "/opt/pi-skills" ] && [ ! -d "$SHARED_SKILLS_VOLUME" ]; then
    cp -r /opt/pi-skills "$SHARED_SKILLS_VOLUME"
    echo "    Copied skills from image"
  elif [ -d "/opt/pi-skills" ]; then
    for skill_dir in /opt/pi-skills/*/; do
      [ -d "$skill_dir" ] || continue
      skill_name=$(basename "$skill_dir")
      if [ ! -d "$SHARED_SKILLS_VOLUME/$skill_name" ]; then
        cp -r "$skill_dir" "$SHARED_SKILLS_VOLUME/$skill_name"
        echo "      → $skill_name"
      fi
    done
  fi

  # --- Generate MCP config (first run) --------------------------------------
  echo "[devstack] Setting up MCP config..."
  MCP_TARGET="${HOME_DIR}/.pi/agent/mcp.json"
  MCP_IMAGE_TEMPLATE="/opt/devstack/mcp.json"
  if [ ! -f "$MCP_TARGET" ] && [ -f "$MCP_IMAGE_TEMPLATE" ]; then
    cp "$MCP_IMAGE_TEMPLATE" "$MCP_TARGET"
    echo "    MCP servers: $(jq -r '.mcpServers | keys[]' "$MCP_TARGET" 2>/dev/null | tr '\n' ', ')"
  fi

  # Mark as initialized
  touch "${HOME_DIR}/.pi/.initialized"
  echo "[devstack] Bootstrap complete."
fi

# --- Pre-configure Lemonade provider (every start) ------------------------
LEMONADE_AUTH="${HOME_DIR}/.pi/agent/auth.json"
LEMONADE_BASE="${LEMONADE_BASE_URL%/v1}"
mkdir -p "${HOME_DIR}/.pi/agent"
if [ ! -f "$LEMONADE_AUTH" ] || ! grep -q '"lemonade"' "$LEMONADE_AUTH" 2>/dev/null; then
  CREDS_PAYLOAD=$(jq -n \
    --arg url "$LEMONADE_BASE" \
    --arg key "lemonade" \
    '{baseUrl: $url, apiKey: $key, serverName: "devstack"}')
  EXPIRES=$(( $(date +%s%3N) + 86400000 ))
  jq -n \
    --argjson payload "$CREDS_PAYLOAD" \
    --argjson expires "$EXPIRES" \
    '{lemonade: {refresh: ($payload | tojson), access: $payload.apiKey, expires: $expires}}' \
    > "$LEMONADE_AUTH"
  echo "[devstack] Pre-configured Lemonade provider"
fi

# --- Wait for Lemonade server ---------------------------------------------
LEMONADE_CHECK_URL="${LEMONADE_BASE}/api/v1/health"
echo "[devstack] Waiting for Lemonade server (max 60s)..."
for i in $(seq 1 60); do
  if curl -sf "${LEMONADE_CHECK_URL}" >/dev/null 2>&1; then
    echo "[devstack] Lemonade server ready"
    break
  fi
  sleep 1
done

# --- Start VSCodium reh-web (foreground) ----------------------------------
ED_PORT="${ED_PORT:-3000}"
EDITOR_HOST="${EDITOR_HOST:-127.0.0.1}"
CONNECTION_TOKEN="${CONNECTION_TOKEN:-devsession}"

exec /opt/vscodium/bin/codium-server serve-web \
  --accept-server-license-terms \
  --host "${EDITOR_HOST}" \
  --port "${ED_PORT}" \
  --connection-token "${CONNECTION_TOKEN}" \
  --default-folder "$WORKSPACE_DIR"
