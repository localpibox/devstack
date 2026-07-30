# ==========================================================================
# Multi-stage Dockerfile — LocalPibox Devstack
# ==========================================================================
# Stage 1 (builder): Heavy build with all deps
# Stage 2 (runtime): Clean image with only runtime artifacts
# ==========================================================================

# ── ARGUMENTS ───────────────────────────────────────────────────────────────
ARG NODE_VERSION=24
ARG PI_PATCH_VERSION=20260730-001
ARG LEMONADE_PATCH_VERSION=20260730-001
ARG VSCODIUM_VERSION=1.126.04524

# ── STAGE 1: BUILDER ───────────────────────────────────────────────────────
FROM ubuntu:26.04 AS builder

ARG NODE_VERSION
ARG PI_PATCH_VERSION
ARG LEMONADE_PATCH_VERSION
ARG VSCODIUM_VERSION

ENV DEBIAN_FRONTEND=noninteractive

# ── Builder: System deps ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-shm0 libx11-xcb1 libx11-6 libxcb1 libxext6 libxrandr2 \
    libxcomposite1 libxcursor1 libxdamage1 libxfixes3 \
    libxi6 libgtk-3-0t64 libpangocairo-1.0-0 libpango-1.0-0 \
    libatk1.0-0t64 libcairo-gobject2 libcairo2 \
    libgdk-pixbuf-2.0-0 libxrender1 libasound2t64 \
    libfreetype6 libfontconfig1 libdbus-1-3 \
    libnss3 libnspr4 libatk-bridge2.0-0t64 \
    libdrm2 libxkbcommon0 libatspi2.0-0 libgbm1 \
    fonts-noto-color-emoji fonts-noto-cjk fonts-freefont-ttf \
    curl ca-certificates gnupg git build-essential pkg-config \
    unzip wget gh \
    python3 python3-pip python3-venv \
    sqlite3 libsqlite3-dev postgresql-client redis-tools \
    ripgrep fzf fd-find jq tmux sudo \
    && rm -rf /var/lib/apt/lists/*

# ── Builder: Node.js ───────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

# ── Builder: Chrome ────────────────────────────────────────────────────────
RUN CHROME_VERSION=$(curl -s https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json | jq -r '.channels.Stable.version') \
       && curl -L "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip" -o /tmp/chrome.zip \
       && mkdir -p /tmp/.agent-browser/browsers/chrome-${CHROME_VERSION} \
       && unzip /tmp/chrome.zip -d /tmp/.agent-browser/browsers/chrome-${CHROME_VERSION} \
       && rm /tmp/chrome.zip

# ── Builder: VSCodium ──────────────────────────────────────────────────────
RUN curl -fsSL \
      "https://github.com/VSCodium/vscodium/releases/download/${VSCODIUM_VERSION}/vscodium-reh-web-linux-x64-${VSCODIUM_VERSION}.tar.gz" \
    -o /tmp/vscodium.tar.gz \
    && mkdir -p /opt/vscodium \
    && tar -xzf /tmp/vscodium.tar.gz -C /opt/vscodium --strip-components=1 \
    && rm /tmp/vscodium.tar.gz

# ── Builder: User setup ────────────────────────────────────────────────────
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
    chown -R 1000:1000 /home/dev

# ── Builder: npm config + base installs ────────────────────────────────────
RUN set -eux; \
    npm config set prefix '/home/dev/.npm-global'; \
    npm config set fetch-retries 5; \
    npm config set fetch-retry-mintimeout 20000; \
    npm config set fetch-retry-maxtimeout 120000; \
    npm config set fetch-timeout 300000; \
    npm config set registry https://registry.npmjs.org/; \
    npm config set allow-scripts '{"agent-browser":true,"better-sqlite3":true,"protobufjs":true,"esbuild":true,"@google/genai":true}'; \
    npm install -g zod@3 agent-browser exa-mcp-server; \
    mkdir -p /home/dev/.npm && chown -R 1000:1000 /home/dev/.npm-global /home/dev/.npm

# ── Builder: Pi monorepo build ─────────────────────────────────────────────
USER root
RUN set -eux; \
    mkdir -p /opt/pi-src && cd /opt/pi-src; \
    git clone --depth=1 --single-branch --branch main https://github.com/earendil-works/pi .; \
    git remote add localpibox https://github.com/localpibox/pi.git 2>/dev/null || true; \
    git fetch localpibox patches/qwen-reasoning-effort 2>/dev/null || true; \
    npm ci --ignore-scripts; \
    # Apply patches
    if ls /opt/pi-patches/*.patch 1>/dev/null 2>&1; then \
        for patch in /opt/pi-patches/*.patch; do \
            git am "$patch" 2>&1; \
        done; \
    fi; \
    npm run build; \
    # Install globally
    npm install -g "./packages/ai" \
        "./packages/agent" \
        "./packages/coding-agent" \
        "./packages/tui"; \
    rm -rf /opt/pi-src/.git

# ── Builder: Pi monorepo build ─────────────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    mkdir -p /opt/pi-src && cd /opt/pi-src; \
    rm -rf /opt/pi-src/* /opt/pi-src/.* 2>/dev/null || true; \
    git clone --depth=1 --single-branch --branch main https://github.com/earendil-works/pi .; \
    git remote add localpibox https://github.com/localpibox/pi.git 2>/dev/null || true; \
    git fetch localpibox patches/qwen-reasoning-effort 2>/dev/null || true; \
    npm ci --ignore-scripts; \
    # Apply patches
    if ls /opt/pi-patches/*.patch 1>/dev/null 2>&1; then \
        for patch in /opt/pi-patches/*.patch; do \
            git am "$patch" 2>&1; \
        done; \
    fi; \
    npm run build; \
    # Install globally
    npm install -g "./packages/ai" \
        "./packages/agent" \
        "./packages/coding-agent" \
        "./packages/tui"; \
    rm -rf /opt/pi-src/.git

# ── Builder: Extensions + Config (robust) ────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    export HOME="/root"; \
    \
    # ── Install extensions ───────────────────────────────────────────────
    echo "=== Installing extensions ==="; \
    pi install git:github.com/localpibox/lemonade-pi-plugin@patches/qwen-vision || echo "WARN: lemonade install failed"; \
    pi install git:github.com/localpibox/pi-hermes-memory@fix/subprocess-provider || echo "WARN: memory install failed"; \
    npm install -g pi-mcp-adapter || echo "WARN: pi-mcp-adapter install failed"; \
    npm install -g @tintinweb/pi-subagents || echo "WARN: pi-subagents install failed"; \
    npm install -g pi-powerline-footer || echo "WARN: pi-powerline-footer install failed"; \
    \
    # ── Clone config repo ────────────────────────────────────────────────
    echo "=== Cloning config repo ==="; \
    mkdir -p /home/dev/.local/pi-config; \
    rm -rf /tmp/pi-config-repo; \
    git clone --depth=1 https://github.com/localpibox/config.git /tmp/pi-config-repo 2>&1 && \
    (cd /tmp/pi-config-repo && cp -r . /home/dev/.local/pi-config/) || echo "WARN: config clone failed"; \
    rm -rf /tmp/pi-config-repo; \
    \
    # ── Copy config files ────────────────────────────────────────────────
    echo "=== Copying config ==="; \
    mkdir -p /home/dev/.pi/agent; \
    [ -f /home/dev/.local/pi-config/settings.json ] && cp /home/dev/.local/pi-config/settings.json /home/dev/.pi/agent/ || echo "WARN: no settings.json"; \
    [ -f /home/dev/.local/pi-config/mcp.json ] && cp /home/dev/.local/pi-config/mcp.json /home/dev/.pi/agent/ || echo "WARN: no mcp.json"; \
    [ -f /home/dev/.local/pi-config/AGENTS.md ] && cp /home/dev/.local/pi-config/AGENTS.md /home/dev/.pi/agent/ || echo "WARN: no AGENTS.md"; \
    \
    # ── Copy skills ──────────────────────────────────────────────────────
    mkdir -p /home/dev/.pi/agent/skills; \
    if [ -d /home/dev/.local/pi-config/skills ]; then \
        for d in /home/dev/.local/pi-config/skills/*/; do \
            [ -d "$d" ] || continue; \
            name=$(basename "$d"); \
            mkdir -p "/home/dev/.pi/agent/skills/$name"; \
            cp "$d"* "/home/dev/.pi/agent/skills/$name/" 2>/dev/null || true; \
            echo "  Skill: $name"; \
        done; \
    fi; \
    \
    # ── Copy agents ──────────────────────────────────────────────────────
    mkdir -p /home/dev/.pi/agent/agents; \
    if [ -d /home/dev/.local/pi-config/agents ]; then \
        cp /home/dev/.local/pi-config/agents/* /home/dev/.pi/agent/agents/ 2>/dev/null || true; \
    fi; \
    \
    # ── Copy support tools ───────────────────────────────────────────────
    echo "=== Copying support tools ==="; \
    mkdir -p /opt/pi-support; \
    if [ -f /home/dev/.local/pi-config/support/start.sh ]; then \
        cp /home/dev/.local/pi-config/support/start.sh /opt/pi-support/start.sh; \
    fi; \
    if [ -f /home/dev/.local/pi-config/support/session-uuid.ts ]; then \
        cp /home/dev/.local/pi-config/support/session-uuid.ts /opt/pi-support/; \
    fi; \
    if [ -f /home/dev/.local/pi-config/support/validate-subagent-output.ts ]; then \
        cp /home/dev/.local/pi-config/support/validate-subagent-output.ts /opt/pi-support/; \
    fi; \
    if [ -f /home/dev/.local/pi-config/support/browser ]; then \
        cp /home/dev/.local/pi-config/support/browser /opt/pi-support/; \
        chmod +x /opt/pi-support/browser; \
    fi; \
    if [ -f /home/dev/.local/pi-config/support/browser-state-cleanup.sh ]; then \
        cp /home/dev/.local/pi-config/support/browser-state-cleanup.sh /opt/pi-support/; \
        chmod +x /opt/pi-support/browser-state-cleanup.sh; \
    fi; \
    if [ -f /home/dev/.local/pi-config/support/browser-validate.ts ]; then \
        cp /home/dev/.local/pi-config/support/browser-validate.ts /opt/pi-support/; \
    fi; \
    mkdir -p /opt/pi-support/config; \
    if [ -d /home/dev/.local/pi-config/support/config ]; then \
        cp /home/dev/.local/pi-config/support/config/* /opt/pi-support/config/ 2>/dev/null || true; \
    fi; \
    mkdir -p /opt/pi-support/docs; \
    if [ -d /home/dev/.local/pi-config/support/docs ]; then \
        cp /home/dev/.local/pi-config/support/docs/* /opt/pi-support/docs/ 2>/dev/null || true; \
    fi; \
    mkdir -p /opt/pi-support/schemas; \
    if [ -d /home/dev/.local/pi-config/support/schemas ]; then \
        cp /home/dev/.local/pi-config/support/schemas/* /opt/pi-support/schemas/ 2>/dev/null || true; \
    fi; \
    \
    # ── Install VSCode extension ─────────────────────────────────────────
    echo "=== Installing VSCode extension ==="; \
    EXT_DIR="/home/dev/.vscodium-server/extensions"; \
    mkdir -p "${EXT_DIR}"; \
    install_ext() { \
        publisher="$1"; name="$2"; \
        meta_url="https://open-vsx.org/api/${publisher}/${name}"; \
        version=$(curl -fsSL "${meta_url}" | jq -r '.version'); \
        if [ -z "$version" ] || [ "$version" = "null" ]; then \
            echo "WARN: no version found for ${publisher}.${name}"; \
            return 0; \
        fi; \
        vsix_url=$(curl -fsSL "${meta_url}" | jq -r '.files.download'); \
        if [ -z "$vsix_url" ] || [ "$vsix_url" = "null" ]; then \
            echo "WARN: no download URL for ${publisher}.${name}"; \
            return 0; \
        fi; \
        dest="${EXT_DIR}/${publisher}.${name}-${version}"; \
        mkdir -p "${dest}"; \
        curl -fsSL "${vsix_url}" -o /tmp/ext.vsix || return 0; \
        rm -rf /tmp/ext_extracted; mkdir -p /tmp/ext_extracted; \
        unzip -q /tmp/ext.vsix -d /tmp/ext_extracted; \
        cp -r /tmp/ext_extracted/extension/. "${dest}/"; \
        rm -rf /tmp/ext.vsix /tmp/ext_extracted; \
        echo "  Installed ${publisher}.${name}@${version}"; \
    }; \
    install_ext pi0 pi-vscode || echo "WARN: pi-vscode install failed"

# ── Builder: Cleanup build deps ────────────────────────────────────────────
RUN apt-get remove -y build-essential git curl wget gnupg unzip; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

USER dev

# ── STAGE 2: RUNTIME ───────────────────────────────────────────────────────
FROM ubuntu:26.04 AS runtime

ARG NODE_VERSION
ARG PI_PATCH_VERSION
ARG LEMONADE_PATCH_VERSION
ARG VSCODIUM_VERSION

ENV DEBIAN_FRONTEND=noninteractive

# ── Runtime: System deps (minimal) ─────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-shm0 libx11-xcb1 libx11-6 libxcb1 libxext6 libxrandr2 \
    libxcomposite1 libxcursor1 libxdamage1 libxfixes3 \
    libxi6 libgtk-3-0t64 libpangocairo-1.0-0 libpango-1.0-0 \
    libatk1.0-0t64 libcairo-gobject2 libcairo2 \
    libgdk-pixbuf-2.0-0 libxrender1 libasound2t64 \
    libfreetype6 libfontconfig1 libdbus-1-3 \
    libnss3 libnspr4 libatk-bridge2.0-0t64 \
    libdrm2 libxkbcommon0 libatspi2.0-0 libgbm1 \
    fonts-noto-color-emoji fonts-noto-cjk fonts-freefont-ttf \
    curl ca-certificates gnupg sudo \
    python3 python3-pip python3-venv \
    ripgrep fzf fd-find jq tmux \
    && rm -rf /var/lib/apt/lists/*

# ── Runtime: Node.js ───────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

# ── Runtime: Copy from builder ─────────────────────────────────────────────
COPY --from=builder /tmp/.agent-browser /home/dev/.agent-browser
COPY --from=builder /opt/vscodium /opt/vscodium
COPY --from=builder /opt/pi-src /opt/pi-src
COPY --from=builder /home/dev/.npm-global /home/dev/.npm-global
COPY --from=builder /home/dev/.npm /home/dev/.npm
COPY --from=builder /home/dev/.pi /home/dev/.pi
COPY --from=builder /home/dev/.local /home/dev/.local
COPY --from=builder /home/dev/.vscodium-server /home/dev/.vscodium-server
COPY --from=builder /opt/pi-support /opt/pi-support

# ── Runtime: Patches + update scripts ──────────────────────────────────────
COPY stack-upkeep/patches/ /opt/pi-patches/
COPY stack-upkeep/scripts/apply-patches.sh /opt/pi-patches/apply-patches.sh
COPY stack-upkeep/scripts/update.sh /opt/pi-patches/update.sh
COPY stack-upkeep/scripts/load-updates.sh /opt/pi-patches/load-updates.sh
RUN chmod +x /opt/pi-patches/apply-patches.sh /opt/pi-patches/update.sh \
    && ln -sf /opt/pi-patches/update.sh /usr/local/bin/stack-update \
    && mkdir -p /opt/pi-internal \
    && ln -sf /opt/pi-patches /opt/pi-internal/stack-upkeep

# ── Runtime: Entrypoint ────────────────────────────────────────────────────
COPY support/start.sh /opt/devstack/start.sh
RUN chmod +x /opt/devstack/start.sh

# ── Runtime: User ──────────────────────────────────────────────────────────
RUN chown -R 1000:1000 /home/dev /opt/pi-src /opt/pi-patches \
    && chmod -R u+rwX /home/dev

USER dev
WORKDIR /home/dev/workspace

ENV PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"
ENV LEMONADE_BASE_URL="http://127.0.0.1:13305/v1"
ENV OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
ENV DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace"
ENV PI_SUPPORT_DIR="/opt/pi-support"

# Labels for publishing
LABEL org.opencontainers.image.title="LocalPibox Devstack" \
      org.opencontainers.image.description="AI-powered dev environment with Pi coding agent" \
      org.opencontainers.image.source="https://github.com/localpibox/devstack" \
      org.opencontainers.image.vendor="LocalPibox" \
      org.opencontainers.image.licenses="MIT"

CMD ["/bin/bash", "/opt/devstack/start.sh"]
