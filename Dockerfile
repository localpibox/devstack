# ==========================================================================
# LocalPibox Devstack — Multi-stage Dockerfile
# ==========================================================================
# Two build targets:
#   cli  — Base dev environment with Pi CLI (interactive terminal)
#   web  — Extends cli + adds VSCodium server + web access
#
# Build:
#   docker build --target cli  -t ghcr.io/localpibox/devstack:cli  .
#   docker build --target web  -t ghcr.io/localpibox/devstack:web  .
# ==========================================================================

ARG NODE_VERSION=24
ARG VSCODIUM_VERSION=1.126.04524
ARG PI_FORK=https://github.com/localpibox/pi.git
ARG PI_BRANCH=patches/qwen-reasoning-effort
ARG PI_HEAD_SHA=unknown

# ═══════════════════════════════════════════════════════════════════════════
# BASE STAGE — Common setup for both cli and web images
# ═══════════════════════════════════════════════════════════════════════════
FROM ubuntu:26.04 AS base

ARG NODE_VERSION
ARG VSCODIUM_VERSION
ARG PI_FORK
ARG PI_BRANCH
ARG PI_HEAD_SHA

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config \
    curl ca-certificates gnupg \
    git jq unzip \
    python3 python3-pip python3-venv libsqlite3-dev \
    sudo \
    gh ripgrep fzf fd-find tmux \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

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

RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/nopasswd && chmod 440 /etc/sudoers.d/nopasswd

RUN set -eux; \
    npm config set prefix '/home/dev/.npm-global'; \
    npm config set fetch-retries 5; \
    npm config set fetch-retry-mintimeout 20000; \
    npm config set fetch-retry-maxtimeout 120000; \
    npm config set fetch-timeout 300000; \
    npm config set registry https://registry.npmjs.org/; \
    npm config set allow-scripts '{"agent-browser":true,"better-sqlite3":true,"protobufjs":true,"esbuild":true,"@google/genai":true}'; \
    npm install -g zod@3 agent-browser exa-mcp-server; \
    npm cache clean --force; \
    chown -R 1000:1000 /home/dev/.npm-global

# ── Pi monorepo build ───────────────────────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    mkdir -p /opt/pi-src && cd /opt/pi-src; \
    git clone --depth=1 --single-branch --branch ${PI_BRANCH} ${PI_FORK} .; \
    git config user.email "build@localpibox.dev"; \
    git config user.name "LocalPibox Build"; \
    npm ci --ignore-scripts; \
    echo "=== Building from pre-patched fork: ${PI_FORK} @ ${PI_BRANCH} (${PI_HEAD_SHA}) ==="; \
    npm run build; \
    mkdir -p /tmp/pi-packs; \
    for pkg in ai agent coding-agent tui; do \
      npm pack "./packages/$pkg" --pack-destination /tmp/pi-packs; \
    done; \
    if [ -d "./packages/client" ]; then \
      npm pack "./packages/client" --pack-destination /tmp/pi-packs; \
    fi; \
    npm install -g /tmp/pi-packs/*.tgz; \
    rm -rf /tmp/pi-packs; \
    /home/dev/.npm-global/bin/pi --version || (echo "FATAL: pi binary not functional" && exit 1); \
    grep -rq 'Case 4' /home/dev/.npm-global/lib/node_modules/@earendil-works/ \
      || (echo "FATAL: Case 4 patch missing from pi-ai" && exit 1); \
    grep -rq 'qwen-chat-template' /home/dev/.npm-global/lib/node_modules/@earendil-works/pi-ai/dist/ \
      || (echo "FATAL: Qwen reasoning_effort patch missing" && exit 1); \
    ls -la /home/dev/.npm-global/bin/; \
    rm -rf /opt/pi-src/.git /opt/pi-src/src /opt/pi-src/test /opt/pi-src/tests

# ── Extensions + Config ─────────────────────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    export HOME="/home/dev"; \
    mkdir -p /home/dev/.local/pi-config; \
    rm -rf /tmp/pi-config-repo; \
    git clone --depth=1 https://github.com/localpibox/config.git /tmp/pi-config-repo 2>&1 && \
    (cd /tmp/pi-config-repo && cp -r . /home/dev/.local/pi-config/) || echo "WARN: config clone failed"; \
    rm -rf /tmp/pi-config-repo; \
    mkdir -p /home/dev/.pi/agent; \
    [ -f /home/dev/.local/pi-config/settings.json ] && cp /home/dev/.local/pi-config/settings.json /home/dev/.pi/agent/ || echo "WARN: no settings.json"; \
    [ -f /home/dev/.local/pi-config/mcp.json ] && cp /home/dev/.local/pi-config/mcp.json /home/dev/.pi/agent/ && sed -i 's/"directTools": true/"directTools": false/' /home/dev/.pi/agent/mcp.json || echo "WARN: no mcp.json"; \
    [ -f /home/dev/.local/pi-config/models.json ] && cp /home/dev/.local/pi-config/models.json /home/dev/.pi/agent/ || echo "WARN: no models.json"; \
    [ -f /home/dev/.local/pi-config/AGENTS.md ] && cp /home/dev/.local/pi-config/AGENTS.md /home/dev/.pi/agent/ || echo "WARN: no AGENTS.md"; \
    [ -f /home/dev/.local/pi-config/SYSTEM.md ] && cp /home/dev/.local/pi-config/SYSTEM.md /home/dev/.pi/agent/ || true; \
    [ -f /home/dev/.local/pi-config/APPEND_SYSTEM.md ] && cp /home/dev/.local/pi-config/APPEND_SYSTEM.md /home/dev/.pi/agent/ || true; \
    mkdir -p /home/dev/.pi/agent/skills; \
    if [ -d /home/dev/.local/pi-config/skills ]; then \
        for d in /home/dev/.local/pi-config/skills/*/; do \
            [ -d "$d" ] || continue; \
            name=$(basename "$d"); \
            mkdir -p "/home/dev/.pi/agent/skills/$name"; \
            cp "$d"* "/home/dev/.pi/agent/skills/$name/" 2>/dev/null || true; \
        done; \
    fi; \
    mkdir -p /home/dev/.pi/agent/agents; \
    [ -d /home/dev/.local/pi-config/agents ] && cp /home/dev/.local/pi-config/agents/* /home/dev/.pi/agent/agents/ 2>/dev/null || true; \
    mkdir -p /opt/pi-support; \
    [ -f /home/dev/.local/pi-config/support/session-uuid.ts ] && cp /home/dev/.local/pi-config/support/session-uuid.ts /opt/pi-support/; \
    [ -f /home/dev/.local/pi-config/support/validate-subagent-output.ts ] && cp /home/dev/.local/pi-config/support/validate-subagent-output.ts /opt/pi-support/; \
    if [ -f /home/dev/.local/pi-config/support/browser ]; then \
        cp /home/dev/.local/pi-config/support/browser /opt/pi-support/; chmod +x /opt/pi-support/browser; \
    fi; \
    if [ -f /home/dev/.local/pi-config/support/browser-state-cleanup.sh ]; then \
        cp /home/dev/.local/pi-config/support/browser-state-cleanup.sh /opt/pi-support/; chmod +x /opt/pi-support/browser-state-cleanup.sh; \
    fi; \
    [ -f /home/dev/.local/pi-config/support/browser-validate.ts ] && cp /home/dev/.local/pi-config/support/browser-validate.ts /opt/pi-support/; \
    mkdir -p /opt/pi-support/config /opt/pi-support/docs /opt/pi-support/schemas; \
    [ -d /home/dev/.local/pi-config/support/config ] && cp /home/dev/.local/pi-config/support/config/* /opt/pi-support/config/ 2>/dev/null || true; \
    [ -d /home/dev/.local/pi-config/support/docs ] && cp /home/dev/.local/pi-config/support/docs/* /opt/pi-support/docs/ 2>/dev/null || true; \
    [ -d /home/dev/.local/pi-config/support/schemas ] && cp /home/dev/.local/pi-config/support/schemas/* /opt/pi-support/schemas/ 2>/dev/null || true; \
    chown -R 1000:1000 /home/dev/.pi /home/dev/.local

# ═══════════════════════════════════════════════════════════════════════════
# CLI IMAGE
# ═══════════════════════════════════════════════════════════════════════════
FROM base AS cli

COPY support/install-browser.sh /opt/devstack/install-browser.sh
COPY support/validate.sh /opt/devstack/validate.sh
COPY support/entrypoint-cli.sh /opt/devstack/entrypoint-cli.sh
RUN ln -sf /opt/devstack/install-browser.sh /usr/local/bin/install-browser \
    && ln -sf /opt/devstack/validate.sh /usr/local/bin/validate-devstack \
    && chmod +x /opt/devstack/install-browser.sh \
           /opt/devstack/validate.sh \
           /opt/devstack/entrypoint-cli.sh

RUN mkdir -p /home/dev/.agent-browser/sessions && chown -R 1000:1000 /home/dev/.agent-browser

RUN chown -R 1000:1000 /home/dev

USER dev
WORKDIR /home/dev/workspace

ENV PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"
ENV LEMONADE_BASE_URL="http://127.0.0.1:13305/v1"
ENV OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
ENV DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace"
ENV PI_SUPPORT_DIR="/opt/pi-support"

LABEL org.opencontainers.image.title="LocalPibox Devstack — CLI" \
      org.opencontainers.image.description="AI-powered dev environment with Pi CLI (interactive terminal)" \
      org.opencontainers.image.source="https://github.com/localpibox/devstack" \
      org.opencontainers.image.vendor="LocalPibox" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["/opt/devstack/entrypoint-cli.sh"]

# ═══════════════════════════════════════════════════════════════════════════
# WEB IMAGE — Extends cli + adds VSCodium + web access
# ═══════════════════════════════════════════════════════════════════════════
FROM cli AS web

RUN curl -fsSL \
      "https://github.com/VSCodium/vscodium/releases/download/${VSCODIUM_VERSION}/vscodium-reh-web-linux-x64-${VSCODIUM_VERSION}.tar.gz" \
    -o /tmp/vscodium.tar.gz \
    && mkdir -p /opt/vscodium \
    && tar -xzf /tmp/vscodium.tar.gz -C /opt/vscodium --strip-components=1 \
    && rm /tmp/vscodium.tar.gz

USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    EXT_DIR="/home/dev/.vscodium-server/extensions"; \
    mkdir -p "${EXT_DIR}"; \
    install_ext() { \
        publisher="$1"; name="$2"; \
        meta_url="https://open-vsx.org/api/${publisher}/${name}"; \
        version=$(curl -fsSL "${meta_url}" | jq -r '.version'); \
        if [ -z "$version" ] || [ "$version" = "null" ]; then echo "WARN: no version for ${publisher}.${name}"; return 0; fi; \
        vsix_url=$(curl -fsSL "${meta_url}" | jq -r '.files.download'); \
        if [ -z "$vsix_url" ] || [ "$vsix_url" = "null" ]; then echo "WARN: no download for ${publisher}.${name}"; return 0; fi; \
        dest="${EXT_DIR}/${publisher}.${name}-${version}"; \
        mkdir -p "${dest}"; \
        curl -fsSL "${vsix_url}" -o /tmp/ext.vsix || return 0; \
        rm -rf /tmp/ext_extracted; mkdir -p /tmp/ext_extracted; \
        unzip -q /tmp/ext.vsix -d /tmp/ext_extracted; \
        cp -r /tmp/ext_extracted/extension/. "${dest}/"; \
        rm -rf /tmp/ext.vsix /tmp/ext_extracted; \
        echo "  Installed ${publisher}.${name}@${version}"; \
    }; \
    install_ext pi0 pi-vscode || echo "WARN: pi-vscode install failed"; \
    chown -R 1000:1000 /home/dev/.vscodium-server

COPY support/entrypoint-web.sh /opt/devstack/entrypoint-web.sh
RUN chmod +x /opt/devstack/entrypoint-web.sh

RUN chown -R 1000:1000 /home/dev

USER dev
WORKDIR /home/dev/workspace

ENV PATH="/opt/vscodium/bin:/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"
ENV LEMONADE_BASE_URL="http://127.0.0.1:13305/v1"
ENV OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
ENV DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace"
ENV PI_SUPPORT_DIR="/opt/pi-support"
ENV ED_PORT="${LPB_ED_PORT:-3000}"
ENV HOST="${LPB_EDITOR_HOST:-0.0.0.0}"
ENV CONNECTION_TOKEN="${LPB_CONNECTION_TOKEN:-devsession}"

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
    CMD curl -sf "http://localhost:${LPB_ED_PORT:-3000}/?tkn=${LPB_CONNECTION_TOKEN:-devsession}" >/dev/null 2>&1 || exit 1

LABEL org.opencontainers.image.title="LocalPibox Devstack — Web" \
      org.opencontainers.image.description="AI-powered dev environment with VSCodium web editor" \
      org.opencontainers.image.source="https://github.com/localpibox/devstack" \
      org.opencontainers.image.vendor="LocalPibox" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["/opt/devstack/entrypoint-web.sh"]
