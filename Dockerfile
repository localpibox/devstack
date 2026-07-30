# ==========================================================================
# Multi-stage Dockerfile — LocalPibox Devstack (minimal)
# ==========================================================================
# Stage 1 (builder): compile native modules, clone repos, assemble artifacts
# Stage 2 (runtime): lean runtime with only what's needed to run
#
# Size savings:
#   - Builder: NO Chrome/X11/GTK/fonts (deferred to install-browser.sh at runtime)
#   - Builder: NO runtime-only tools (ripgrep, fzf, jq, tmux, gh, unzip)
#   - Builder: NO unused DB clients (postgresql-client, redis-tools)
#   - Runtime: NO /opt/pi-src (pi packages installed globally in .npm-global)
#   - Runtime: NO build-essential, python3, or build deps
#   - Runtime: user created BEFORE COPY files (correct UID 1000 ownership)
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

# ── Builder: Build deps + tools needed for extension/config install ─────────
# Chrome/X11/GTK fonts dropped — browser installed on-demand at runtime.
# jq/unzip kept here — used by extension installer (open-vsx API, VSIX extract).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config \
    curl ca-certificates gnupg \
    git jq unzip \
    python3 python3-pip python3-venv \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Builder: Node.js ───────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

# ── Builder: VSCodium ──────────────────────────────────────────────────────
RUN curl -fsSL \
      "https://github.com/VSCodium/vscodium/releases/download/${VSCODIUM_VERSION}/vscodium-reh-web-linux-x64-${VSCODIUM_VERSION}.tar.gz" \
    -o /tmp/vscodium.tar.gz \
    && mkdir -p /opt/vscodium \
    && tar -xzf /tmp/vscodium.tar.gz -C /opt/vscodium --strip-components=1 \
    && rm /tmp/vscodium.tar.gz

# ── Builder: User setup (matches runtime UID 1000) ─────────────────────────
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

# ── Builder: npm config + global installs ──────────────────────────────────
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

# ── Builder: Pi monorepo build (single pass) ───────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    mkdir -p /opt/pi-src && cd /opt/pi-src; \
    rm -rf /opt/pi-src/* /opt/pi-src/.* 2>/dev/null || true; \
    git clone --depth=1 --single-branch --branch main https://github.com/earendil-works/pi .; \
    git remote add localpibox https://github.com/localpibox/pi.git 2>/dev/null || true; \
    git fetch localpibox patches/qwen-reasoning-effort 2>/dev/null || true; \
    npm ci --ignore-scripts; \
    if ls /opt/pi-patches/*.patch 1>/dev/null 2>&1; then \
        for patch in /opt/pi-patches/*.patch; do \
            git am "$patch" 2>&1; \
        done; \
    fi; \
    npm run build; \
    mkdir -p /tmp/pi-packs; \
    for pkg in ai agent coding-agent tui; do \
      npm pack "./packages/$pkg" --pack-destination /tmp/pi-packs; \
    done; \
    npm install -g /tmp/pi-packs/*.tgz; \
    ls -la /home/dev/.npm-global/bin/; \
    rm -rf /opt/pi-src/.git /opt/pi-src/src /opt/pi-src/test /opt/pi-src/tests /tmp/pi-packs

# ── Builder: Extensions + Config ───────────────────────────────────────────
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

# ── STAGE 2: RUNTIME ───────────────────────────────────────────────────────
# Purpose: runtime dependencies + copied artifacts
# Browser installed on-demand: user runs `agent-browser install` + `--with-deps`
FROM ubuntu:26.04 AS runtime

ARG NODE_VERSION
ARG PI_PATCH_VERSION
ARG LEMONADE_PATCH_VERSION
ARG VSCODIUM_VERSION

ENV DEBIAN_FRONTEND=noninteractive

# ── Runtime: Minimal apt — NO Chrome/X11 libs (installed on-demand) ────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg sudo \
    git unzip gh \
    ripgrep fzf fd-find jq tmux \
    && rm -rf /var/lib/apt/lists/*

# ── Runtime: Node.js ───────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && corepack enable

# ── Runtime: Create dev user (MUST be before COPY — files use UID 1000) ────
# Ubuntu 26.04 base may already have a user with UID 1000 (e.g. "ubuntu");
# rename it to "dev" if so.
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
    fi

# ── Runtime: Copy from builder ─────────────────────────────────────────────
COPY --from=builder /opt/vscodium /opt/vscodium
COPY --from=builder /home/dev/.npm-global /home/dev/.npm-global
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

# ── Runtime: Helper scripts ────────────────────────────────────────────────
COPY support/start.sh /opt/devstack/start.sh
COPY support/install-browser.sh /opt/devstack/install-browser.sh
COPY run.sh /usr/local/bin/run.sh
COPY stack.sh /usr/local/bin/stack.sh
COPY build-updates.sh /usr/local/bin/build-updates.sh
COPY load-updates.sh /usr/local/bin/load-updates.sh
RUN chmod +x /opt/devstack/start.sh \
    /opt/devstack/install-browser.sh \
    /usr/local/bin/run.sh /usr/local/bin/stack.sh \
    /usr/local/bin/build-updates.sh /usr/local/bin/load-updates.sh

# ── Runtime: User ──────────────────────────────────────────────────────────
# Set ownership on copied directories. Dev user exists (created above).
RUN chown -R 1000:1000 /home/dev /opt/pi-patches \
    && chmod -R u+rwX /home/dev

USER dev
WORKDIR /home/dev/workspace

ENV PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"
ENV LEMONADE_BASE_URL="http://127.0.0.1:13305/v1"
ENV OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
ENV DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace"
ENV PI_SUPPORT_DIR="/opt/pi-support"

LABEL org.opencontainers.image.title="LocalPibox Devstack" \
      org.opencontainers.image.description="AI-powered dev environment with Pi coding agent" \
      org.opencontainers.image.source="https://github.com/localpibox/devstack" \
      org.opencontainers.image.vendor="LocalPibox" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["/opt/devstack/start.sh"]
