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
    # Explicitly set prefix to avoid fallback to /usr/lib/node_modules
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
  npm_install_global @fission-ai/openspec
  pi_install pi-hermes-memory
  pi_install pi-mcp-adapter
  npm_install_global exa-mcp-server
  npm_install_global agent-browser
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

  # --- Install support tools to PATH ----------------------------------------
  echo "[devstack] Installing support tools..."
  if [ -d "$PI_SUPPORT_DIR" ]; then
    for script in "$PI_SUPPORT_DIR"/*.sh; do
      [ -f "$script" ] || continue
      sudo cp "$script" "/usr/local/bin/$(basename "$script")"
      sudo chmod +x "/usr/local/bin/$(basename "$script")"
    done
    GLOBAL_NPM_MODS="$(npm root -g)"
    for ts in "$PI_SUPPORT_DIR"/*.ts; do
      [ -f "$ts" ] || continue
      name=$(basename "$ts" .ts)
      {
        cat <<'WRAPPER'
#!/usr/bin/env bash
export NODE_PATH="${GLOBAL_NPM_DIR}${NODE_PATH:+:$NODE_PATH}"
exec npx tsx "$PI_SUPPORT_DIR"/"$0" "$@"
WRAPPER
      } > "/tmp/devstack-wrapper-$name"
      sed -i "s/\${GLOBAL_NPM_DIR}/$(echo "$GLOBAL_NPM_MODS" | sed 's/[&/\\]/\\&/g')/" "/tmp/devstack-wrapper-$name"
      sudo cp "/tmp/devstack-wrapper-$name" "/usr/local/bin/$name"
      sudo chmod +x "/usr/local/bin/$name"
    done
    for exe in "$PI_SUPPORT_DIR"/*; do
      [ -f "$exe" ] || continue
      case "$exe" in *.sh|*.ts|*.json|*.txt|*.md|*.yml|*.yaml|*.png|*.jpg|*.jpeg) continue ;; esac
      name=$(basename "$exe")
      if [ ! -f "/usr/local/bin/$name" ]; then
        sudo cp "$exe" "/usr/local/bin/$name"
        sudo chmod +x "/usr/local/bin/$name" 2>/dev/null || true
      fi
    done
    echo "    Support tools installed"
  fi

  # --- Generate MCP config (first run) --------------------------------------
  # Copy the image template to ~/.pi/agent/mcp.json (base config).
  # The pi-mcp-adapter automatically merges workspace .mcp.json files from
  # standard locations — no hardcoded workspace paths needed.
  echo "[devstack] Setting up MCP config..."
  MCP_TARGET="${HOME_DIR}/.pi/agent/mcp.json"
  MCP_IMAGE_TEMPLATE="/opt/devstack/mcp.json"
  if [ ! -f "$MCP_TARGET" ] && [ -f "$MCP_IMAGE_TEMPLATE" ]; then
    cp "$MCP_IMAGE_TEMPLATE" "$MCP_TARGET"
    echo "    MCP servers: $(jq -r '.mcpServers | keys[]' "$MCP_TARGET" 2>/dev/null | tr '\n' ', ')"
  elif [ -f "$MCP_TARGET" ]; then
    echo "    MCP config already exists at $MCP_TARGET"
  else
    echo "    [WARN] No MCP template found at $MCP_IMAGE_TEMPLATE"
  fi

  # Install project dependencies
  echo "[devstack] Installing project dependencies..."
  cd "$WORKSPACE_DIR"
  npm install 2>&1 | tail -1 || echo "    [WARN] npm install failed"

  # Mark as initialized
  touch "${HOME_DIR}/.pi/.initialized"
  echo "[devstack] Bootstrap complete."
fi

# --- Pre-configure Lemonade provider (every start) ------------------------
# The lemonade-pi-plugin reads auth.json on startup and auto-registers the
# provider if credentials are found.
LEMONADE_AUTH="${HOME_DIR}/.pi/agent/auth.json"
LEMONADE_URL="${LEMONADE_BASE_URL}"
LEMONADE_BASE="${LEMONADE_URL%/v1}"
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
else
  echo "[devstack] Lemonade auth already configured"
fi

# --- Wait for Lemonade server ---------------------------------------------
LEMONADE_CHECK_URL="${LEMONADE_BASE}/api/v1/health"
echo "[devstack] Waiting for Lemonade server (max 60s)..."
LEMONADE_READY=false
for i in $(seq 1 60); do
  if curl -sf "${LEMONADE_CHECK_URL}" >/dev/null 2>&1; then
    LEMONADE_READY=true
    echo "[devstack] Lemonade server ready"
    break
  fi
  sleep 1
done
if [ "$LEMONADE_READY" != "true" ]; then
  echo "[devstack] WARNING: Lemonade not reachable — Pi may fall back to cloud providers"
fi

# --- Browser state cleanup (every start) ----------------------------------
echo "[devstack] Cleaning browser states..."
bash /usr/local/bin/browser-state-cleanup 2>/dev/null || true

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
