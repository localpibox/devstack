# ═══════════════════════════════════════════════════════════════════════════
# LOCALPIBOX DEVSTACK — MULTI-STAGE DOCKERFILE
# ═══════════════════════════════════════════════════════════════════════════
# Two build targets:
#   cli  — Base dev environment with Pi CLI (interactive terminal)
#   web  — Extends cli + adds VSCodium server + web access
#
# Build:
#   docker build --target cli  -t ghcr.io/localpibox/devstack:cli  .
#   docker build --target web  -t ghcr.io/localpibox/devstack:web  .
#
# Fork configuration: lpb.stack.env (project root)
#   Sourced at build time to populate ARG defaults:
#   LPB_PI_FORK, LPB_PI_REF, LPB_NODE_VERSION, LPB_VSCODIUM_VERSION
#
# NOTE: Runtime extensions (lemonade-pi-plugin, pi-hermes-memory) are NOT
#       built into the image. They are cloned at container startup by
#       `pi update --extensions`, which reads their branches from
#       .pi/agent/settings.json → "packages" array.
# ═══════════════════════════════════════════════════════════════════════════

# Source fork configuration — ARG defaults come from lpb.stack.env
# NOTE: Docker ARG values can't reference source'd shell variables.
# The ARGs below are the definitive defaults. CI sets them via
#   docker build --build-arg PI_FORK=... etc.
ARG NODE_VERSION=24
ARG VSCODIUM_VERSION=1.126.04524
ARG PI_FORK=https://github.com/localpibox/pi.git
ARG PI_REF=lpb
ARG PI_HEAD_SHA=unknown

# ═══════════════════════════════════════════════════════════════════════════
# BASE STAGE — Common setup for both cli and web images
# ═══════════════════════════════════════════════════════════════════════════
FROM ubuntu:26.04 AS base

ARG NODE_VERSION
ARG VSCODIUM_VERSION
ARG PI_FORK
ARG PI_REF
ARG PI_HEAD_SHA

ENV DEBIAN_FRONTEND=noninteractive

# Context window / max tokens ratio — baked into image.
# 0.06 (6%) — reduced from 0.125 for Qwen thinking models.
# Container-level overrides take precedence via --env or -e at runtime.
ENV LPB_MAX_TOKENS_CONTEXT_RATIO=0.06
ENV LPB_VERSION=

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config \
    curl ca-certificates gnupg \
    git jq unzip rsync \
    python3 python3-pip python3-venv libsqlite3-dev \
    sudo openssh-server openssl \
    gh ripgrep fzf fd-find tmux \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

RUN set -eux; \
    if getent passwd 1000 >/dev/null; then \
      oldname="$(getent passwd 1000 | cut -d: -f1)"; \
      if [ "$oldname" != "lpb" ]; then \
        usermod -l lpb -d /home/lpb -m "$oldname"; \
        if getent group 1000 >/dev/null; then \
          oldgroup="$(getent group 1000 | cut -d: -f1)"; \
          [ "$oldgroup" = "lpb" ] || groupmod -n lpb "$oldgroup"; \
        fi; \
      fi; \
    else \
      useradd -m -s /bin/bash -u 1000 lpb; \
    fi; \
    chown -R 1000:1000 /home/lpb

RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/nopasswd && chmod 440 /etc/sudoers.d/nopasswd

RUN set -eux; \
    npm config set prefix '/home/lpb/.npm-global'; \
    npm config set fetch-retries 5; \
    npm config set fetch-retry-mintimeout 20000; \
    npm config set fetch-retry-maxtimeout 120000; \
    npm config set fetch-timeout 300000; \
    npm config set registry https://registry.npmjs.org/; \
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > /home/lpb/.npmrc; \
    # Write .npmrc to git install root so all extensions inherit allow-scripts
    mkdir -p /home/lpb/.pi/agent/git && \
    printf 'allow-scripts=better-sqlite3\nallow-scripts=agent-browser\nallow-scripts=esbuild\nallow-scripts=protobufjs\nallow-scripts=@google/genai\n' > /home/lpb/.pi/agent/git/.npmrc; \
    npm install -g zod@3 agent-browser exa-mcp-server; \
    npm cache clean --force; \
    chown -R 1000:1000 /home/lpb/.npm-global

# ── Pi monorepo build ───────────────────────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/lpb/.npm-global/bin:${PATH}"; \
    mkdir -p /opt/pi-src && cd /opt/pi-src; \
    git clone --depth=1 --single-branch --branch ${PI_REF} ${PI_FORK} .; \
    git config user.email "build@localpibox.dev"; \
    git config user.name "LocalPibox Build"; \
    npm install; \
    ln -sf "$(pwd)/node_modules/@typescript/native-preview-linux-x64/lib/tsgo" "$(pwd)/node_modules/.bin/tsgo"; \
    export PATH="$(pwd)/node_modules/.bin:${PATH}"; \
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
    /home/lpb/.npm-global/bin/pi --version || (echo "FATAL: pi binary not functional" && exit 1); \
    grep -rq 'Case 4' /home/lpb/.npm-global/lib/node_modules/@earendil-works/ \
      || (echo "FATAL: Case 4 patch missing from pi-ai" && exit 1); \
    grep -rq 'qwen-chat-template' /home/lpb/.npm-global/lib/node_modules/@earendil-works/pi-ai/dist/ \
      || (echo "FATAL: Qwen reasoning_effort patch missing" && exit 1); \
    ls -la /home/lpb/.npm-global/bin/; \
    rm -rf /opt/pi-src/.git /opt/pi-src/src /opt/pi-src/test /opt/pi-src/tests

# ── Extensions + Config ─────────────────────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/lpb/.npm-global/bin:${PATH}"; \
    export HOME="/home/lpb"; \
    mkdir -p /home/lpb/.local/pi-config; \
    rm -rf /tmp/pi-config-repo; \
    git clone --depth=1 --branch main https://github.com/localpibox/config.git /tmp/pi-config-repo 2>&1 && \
    (cd /tmp/pi-config-repo && cp -r . /home/lpb/.local/pi-config/) || echo "WARN: config clone failed"; \
    rm -rf /tmp/pi-config-repo; \
    # Copy lpb.conf.env into the image for start.sh to load at runtime \
    [ -f /opt/devstack/lpb.conf.env ] && cp /opt/devstack/lpb.conf.env /home/lpb/.local/lpb.conf.env || echo "WARN: no lpb.conf.env"; \
    mkdir -p /home/lpb/.pi/agent; \
    [ -f /home/lpb/.local/pi-config/settings.json ] && cp /home/lpb/.local/pi-config/settings.json /home/lpb/.pi/agent/ || echo "WARN: no settings.json"; \
    [ -f /home/lpb/.local/pi-config/mcp.json ] && cp /home/lpb/.local/pi-config/mcp.json /home/lpb/.pi/agent/ || echo "WARN: no mcp.json"; \
    [ -f /home/lpb/.local/pi-config/hermes-memory-config.json ] && cp /home/lpb/.local/pi-config/hermes-memory-config.json /home/lpb/.pi/agent/ || echo "WARN: no hermes-memory-config.json"; \
    [ -f /home/lpb/.local/pi-config/pi-defaults.json ] && cp /home/lpb/.local/pi-config/pi-defaults.json /home/lpb/.pi/agent/ || echo "WARN: no pi-defaults.json"; \
    [ -f /home/lpb/.local/pi-config/subagents.json ] && cp /home/lpb/.local/pi-config/subagents.json /home/lpb/.pi/agent/ || echo "WARN: no subagents.json"; \
    [ -f /home/lpb/.local/pi-config/models.json ] && cp /home/lpb/.local/pi-config/models.json /home/lpb/.pi/agent/ || echo "WARN: no models.json"; \
    [ -f /home/lpb/.local/pi-config/AGENTS.md ] && cp /home/lpb/.local/pi-config/AGENTS.md /home/lpb/.pi/agent/ || echo "WARN: no AGENTS.md"; \
    [ -f /home/lpb/.local/pi-config/SYSTEM.md ] && cp /home/lpb/.local/pi-config/SYSTEM.md /home/lpb/.pi/agent/ || true; \
    [ -f /home/lpb/.local/pi-config/APPEND_SYSTEM.md ] && cp /home/lpb/.local/pi-config/APPEND_SYSTEM.md /home/lpb/.pi/agent/ || true; \
    mkdir -p /home/lpb/.pi/agent/skills; \
    if [ -d /home/lpb/.local/pi-config/skills ]; then \
        for d in /home/lpb/.local/pi-config/skills/*/; do \
            [ -d "$d" ] || continue; \
            name=$(basename "$d"); \
            mkdir -p "/home/lpb/.pi/agent/skills/$name"; \
            cp "$d"* "/home/lpb/.pi/agent/skills/$name/" 2>/dev/null || true; \
        done; \
    fi; \
    mkdir -p /home/lpb/.pi/agent/agents; \
    if [ -d /home/lpb/.local/pi-config/agents ]; then \
        rsync -a --delete /home/lpb/.local/pi-config/agents/ /home/lpb/.pi/agent/agents/ 2>/dev/null || \
        cp -r /home/lpb/.local/pi-config/agents/* /home/lpb/.pi/agent/agents/ 2>/dev/null || true; \
    fi; \
    chown -R 1000:1000 /home/lpb/.pi /home/lpb/.local

# ═══════════════════════════════════════════════════════════════════════════
# CLI IMAGE
# ═══════════════════════════════════════════════════════════════════════════
FROM base AS cli

# ── Support utilities (moved from config/support/ to devstack/support/) ──
# Copied to /opt/pi-support/ — used by start.sh at runtime
COPY support/browser-state-cleanup.sh /opt/pi-support/browser-state-cleanup.sh
COPY support/browser-validate.ts /opt/pi-support/browser-validate.ts
COPY support/session-uuid.ts /opt/pi-support/session-uuid.ts
COPY support/validate-subagent-output.ts /opt/pi-support/validate-subagent-output.ts
COPY support/config/ /opt/pi-support/config/
COPY support/docs/ /opt/pi-support/docs/
COPY support/schemas/ /opt/pi-support/schemas/
RUN chmod +x /opt/pi-support/browser-state-cleanup.sh

# ── Devstack deployment scripts ──
COPY support/install-browser.sh /opt/devstack/install-browser.sh
COPY support/validate.sh /opt/devstack/validate.sh
COPY support/install-openspec.sh /opt/pi-support/install-openspec.sh
COPY support/start.sh /opt/devstack/start.sh
COPY lpb.conf.env /opt/devstack/lpb.conf.env
COPY support/entrypoint-cli.sh /opt/devstack/entrypoint-cli.sh
RUN ln -sf /opt/devstack/install-browser.sh /usr/local/bin/install-browser \
    && ln -sf /opt/devstack/validate.sh /usr/local/bin/validate-devstack \
    && ln -sf /opt/pi-support/install-openspec.sh /usr/local/bin/install-openspec \
    && chmod +x /opt/devstack/install-browser.sh \
           /opt/devstack/validate.sh \
           /opt/devstack/start.sh \
           /opt/devstack/entrypoint-cli.sh \
           /opt/pi-support/install-openspec.sh

RUN mkdir -p /home/lpb/.agent-browser/sessions && chown -R 1000:1000 /home/lpb/.agent-browser

# ─── Git credential helper ────────────────────────────────────────────
# Points git to gh auth for GitHub HTTPS operations. No sensitive data
# baked in — the actual token is resolved at runtime from
# /home/lpb/.config/gh/hosts.yml (volume-mounted from host).
RUN printf '[credential "https://github.com"]\n    helper = !gh auth git-credential\n[credential "https://gist.github.com"]\n    helper = !gh auth git-credential\n' > /home/lpb/.gitconfig && chown 1000:1000 /home/lpb/.gitconfig

RUN chown -R 1000:1000 /home/lpb

# ─── Shell PATH (npm global bin, local bin) ──────────────────────────
# Ensures agent-browser, pi, and other npm-global tools are on PATH
# for all interactive and non-interactive shells.
RUN printf '\n# LocalPibox: npm-global and local bin on PATH\nexport PATH="/home/lpb/.npm-global/bin:/home/lpb/.local/bin:${PATH}"\n' >> /home/lpb/.bashrc

USER lpb
WORKDIR /home/lpb/workspace

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

# ── VSCodium ────────────────────────────────────────────────────────────────
USER root
RUN curl -fsSL \
      "https://github.com/VSCodium/vscodium/releases/download/${VSCODIUM_VERSION}/vscodium-reh-web-linux-x64-${VSCODIUM_VERSION}.tar.gz" \
    -o /tmp/vscodium.tar.gz \
    && mkdir -p /opt/vscodium \
    && tar -xzf /tmp/vscodium.tar.gz -C /opt/vscodium --strip-components=1 \
    && rm /tmp/vscodium.tar.gz

USER root
RUN set -eux; \
    export PATH="/home/lpb/.npm-global/bin:${PATH}"; \
    EXT_DIR="/home/lpb/.vscodium-server/extensions"; \
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
    chown -R 1000:1000 /home/lpb/.vscodium-server

COPY support/entrypoint-web.sh /opt/devstack/entrypoint-web.sh
RUN chmod +x /opt/devstack/entrypoint-web.sh

RUN chown -R 1000:1000 /home/lpb

USER lpb
WORKDIR /home/lpb/workspace

ENV ED_PORT=3000
ENV HOST=0.0.0.0
# Auto-generated random token on container start.
# Override with --env CONNECTION_TOKEN=xxx or set a fixed value for persistence.
ENV CONNECTION_TOKEN=

# Healthcheck uses bare names (VSCodium server reads them)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
    CMD curl -sf "http://localhost:${ED_PORT}/" >/dev/null 2>&1 && curl -sf "http://localhost:${ED_PORT}/?tkn=${CONNECTION_TOKEN:-}" >/dev/null 2>&1 || exit 1

LABEL org.opencontainers.image.title="LocalPibox Devstack — Web" \
      org.opencontainers.image.description="AI-powered dev environment with VSCodium web editor" \
      org.opencontainers.image.source="https://github.com/localpibox/devstack" \
      org.opencontainers.image.vendor="LocalPibox" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["/opt/devstack/entrypoint-web.sh"]
