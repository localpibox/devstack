ARG NODE_VERSION=24

# Ubuntu 26.04 LTS — base for the devstack container.
# Runs VSCodium reh-web (browser editor) + PI Agent MCP (tools/chat).
FROM ubuntu:26.04

ARG NODE_VERSION
# ==========================================================================
# LAYER 1 — apt-get packages (only changes when packages change)
# ==========================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-shm0 \
    libx11-xcb1 libx11-6 libxcb1 libxext6 libxrandr2 \
    libxcomposite1 libxcursor1 libxdamage1 libxfixes3 \
    libxi6 libgtk-3-0t64 libpangocairo-1.0-0 libpango-1.0-0 \
    libatk1.0-0t64 libcairo-gobject2 libcairo2 \
    libgdk-pixbuf-2.0-0 libxrender1 libasound2t64 \
    libfreetype6 libfontconfig1 libdbus-1-3 \
    libnss3 libnspr4 libatk-bridge2.0-0t64 \
    libdrm2 libxkbcommon0 libatspi2.0-0t64 \
    libcups2t64 libxshmfence1 libgbm1 \
    fonts-noto-color-emoji fonts-noto-cjk fonts-freefont-ttf \
    curl ca-certificates gnupg git build-essential pkg-config \
    unzip wget gh \
    python3 python3-pip python3-venv \
    sqlite3 libsqlite3-dev postgresql-client redis-tools \
    ripgrep fzf fd-find jq tmux sudo \
    && rm -rf /var/lib/apt/lists/*

# ==========================================================================
# LAYER 2 — Node.js (stable, only changes when Node version changes)
# ==========================================================================
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

# ==========================================================================
# LAYER 3 — VSCodium download (heavy, ~100MB, changes only on version bump)
# ==========================================================================
ARG VSCODIUM_VERSION=1.126.0
ARG VSCODIUM_COMMIT=4524
RUN curl -fsSL \
      "https://github.com/VSCodium/vscodium/releases/download/${VSCODIUM_VERSION}${VSCODIUM_COMMIT}/vscodium-reh-web-linux-x64-${VSCODIUM_VERSION}${VSCODIUM_COMMIT}.tar.gz" \
    -o /tmp/vscodium.tar.gz \
    && mkdir -p /opt/vscodium \
    && tar -xzf /tmp/vscodium.tar.gz -C /opt/vscodium --strip-components=1 \
    && rm /tmp/vscodium.tar.gz

# ==========================================================================
# LAYER 4 — Chrome download (heaviest, ~150MB+, changes on Chrome updates)
#         Downloaded at build time so agent-browser works without host Chrome.
#         Build into /tmp first to avoid creating /home/dev (conflicts with
#         usermod -m in Layer 5).
# ==========================================================================
RUN CHROME_VERSION=$(curl -s https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json | jq -r '.channels.Stable.version') \
       && curl -L "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip" -o /tmp/chrome.zip \
       && mkdir -p /tmp/.agent-browser/browsers/chrome-${CHROME_VERSION} \
       && unzip /tmp/chrome.zip -d /tmp/.agent-browser/browsers/chrome-${CHROME_VERSION} \
       && rm /tmp/chrome.zip \
       && chown -R 1000:1000 /tmp/.agent-browser \
       && echo "Chrome ${CHROME_VERSION} installed"

# ==========================================================================
# LAYER 5 — User setup + npm installs + agent-browser (ALL in ONE RUN)
#         Each RUN creates a layer.  rm -rf cleans temp dirs at the end.
# ==========================================================================
RUN set -eux; \
    if getent passwd 1000 >/dev/null; then \
      oldname="$(getent passwd 1000 | cut -d: -f1)"; \
      if [ "$oldname" != "dev" ]; then \
        usermod -l dev -d /home/dev -m "$oldname"; \
        if getent group 1000 >/dev/null; then \
          oldgroup="$(getent group 1000 | cut -d: -f1)"; \
          [ "$oldgroup" = "dev" ] || groupmod -n dev "$oldgroup"; \
        fi; \
      fi; \
    else \
      useradd -m -s /bin/bash -u 1000 dev; \
    fi; \
    mv /tmp/.agent-browser /home/dev/.agent-browser && chown -R 1000:1000 /home/dev/.agent-browser; \
    echo "dev ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/dev && chmod 0440 /etc/sudoers.d/dev; \
    npm config set prefix '/home/dev/.npm-global'; \
    npm config set fetch-retries 5; \
    npm config set fetch-retry-mintimeout 30000; \
    npm config set fetch-retry-maxtimeout 300000; \
    npm config set fetch-timeout 600000; \
    npm config set allow-scripts 'agent-browser'; \
    npm install -g zod@3; \
    npm install -g @earendil-works/pi-coding-agent; \
    npm install -g agent-browser exa-mcp-server; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    mkdir -p /home/dev/.npm && chown -R 1000:1000 /home/dev/.npm-global /home/dev/.npm; \
    rm -rf /tmp/* /var/tmp/*

USER dev
WORKDIR /home/dev/workspace
ENV PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"

# ==========================================================================
# LAYER 6 — Pi plugin installs (cached by pi, fast rebuild)
#         Each install is idempotent (|| true for first-run safety).
#         Also installs the global researcher agent for subagents.
# ==========================================================================
RUN pi install npm:pi-hermes-memory || true \
    && pi install npm:pi-mcp-adapter || true \
    && pi install git:github.com/localpibox/lemonade-pi-plugin@main || true \
    && pi install npm:@tintinweb/pi-subagents || true \
    && mkdir -p /home/dev/.pi/agent/agents && chown -R 1000:1000 /home/dev/.pi/agent/agents

# ==========================================================================
# LAYER 7 — Shared Pi skills (changes occasionally)
# ==========================================================================
COPY skills /opt/pi-skills

# ==========================================================================
# LAYER 8 — Support tools (changes occasionally)
# ==========================================================================
COPY support /opt/pi-support

# ==========================================================================
# LAYER 9 — Config files that change rarely (stable configs)
# ==========================================================================
COPY mcp.json /opt/devstack/mcp.json
COPY extensions.json /opt/devstack/extensions.json

# ==========================================================================
# Install extensions at build time — fetch from open-vsx.org, unpack vsix,
# no running server or IPC hook required.
# ==========================================================================
RUN set -eux; \
    EXT_DIR="/home/dev/.vscodium-server/extensions"; \
    mkdir -p "${EXT_DIR}"; \
    install_ext() { \
        publisher="$1"; name="$2"; \
        meta_url="https://open-vsx.org/api/${publisher}/${name}"; \
        version=$(curl -fsSL "${meta_url}" | jq -r '.version'); \
        vsix_url=$(curl -fsSL "${meta_url}" | jq -r '.files.download'); \
        dest="${EXT_DIR}/${publisher}.${name}-${version}"; \
        mkdir -p "${dest}"; \
        curl -fsSL "${vsix_url}" -o /tmp/ext.vsix; \
        rm -rf /tmp/ext_extracted; mkdir -p /tmp/ext_extracted; \
        unzip -q /tmp/ext.vsix -d /tmp/ext_extracted; \
        cp -r /tmp/ext_extracted/extension/. "${dest}/"; \
        rm -rf /tmp/ext.vsix /tmp/ext_extracted; \
        echo "Installed ${publisher}.${name}@${version}"; \
    }; \
    install_ext pi0 pi-vscode

RUN mkdir -p /home/dev/.config/codium/User
COPY settings.json /home/dev/.config/codium/User/settings.json

# ==========================================================================
# LAYER 9b — Global Pi agents (deployed to ~/.pi/agent/agents/)
# ==========================================================================
COPY agents /opt/pi-agents
RUN mkdir -p /home/dev/.pi/agent/agents && cp /opt/pi-agents/*.md /home/dev/.pi/agent/agents/ 2>/dev/null || true && chown -R 1000:1000 /home/dev/.pi/agent/agents

# ==========================================================================
# LAYER 10 — Start script (changes frequently — kept last for cache isolation)
# ==========================================================================
COPY support/start.sh /opt/devstack/start.sh
USER root
RUN chmod +x /opt/devstack/start.sh
USER dev

# ==========================================================================
# ENV + Entrypoint
# ==========================================================================
ENV LEMONADE_BASE_URL="http://127.0.0.1:13305/v1"
ENV OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
ENV DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace"
ENV PI_SUPPORT_DIR="/opt/pi-support"

# --- Entrypoint: start MCP + VSCodium -------------------------------------
CMD ["/bin/bash", "/opt/devstack/start.sh"]
