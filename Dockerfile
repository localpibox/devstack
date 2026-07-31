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
#   - Runtime: build-essential + python3 + libsqlite3-dev for native module rebuild
#   - Runtime: user created BEFORE COPY files (correct UID 1000 ownership)
#
# Fixes applied vs. previous version:
#   1. /opt/pi-patches is now COPYed into the BUILDER stage (was only in
#      runtime stage) — patches were previously silently skipped, so the
#      "patched" pi build was actually unpatched upstream.
#   2. Removed `export HOME="/root"` before `pi install git:...` calls —
#      it caused those two extensions to install into /root/.pi, which is
#      never copied into the runtime image and was silently discarded.
#   3. Removed the unused `git remote add localpibox` / `git fetch` lines —
#      patch files under /opt/pi-patches/*.patch are the preferred,
#      single mechanism now; no half-wired second patch path.
#   4. Removed the `rm -rf /opt/pi-src/* /opt/pi-src/.*` glob — `.* ` also
#      expands to `..` (parent dir); redundant anyway since the dir is
#      freshly created in the same layer.
#   5. Added `models.json` to the config-copy step (was missing — this was
#      the root cause of the earlier Lemonade max-output-tokens issue).
#   6. Added a build-time smoke test (`pi --version`) so a broken/missing
#      binary fails the build loudly instead of silently producing a
#      broken image.
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

# ── Builder: Patch files (copied here so the pi build step below can see
#             them — must be available in the BUILDER stage, not just
#             runtime, or `git am` silently finds nothing to apply) ────────
COPY stack-upkeep/patches/ /opt/pi-patches/

# ── Builder: Pi monorepo build (single pass) ───────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    mkdir -p /opt/pi-src && cd /opt/pi-src; \
    git clone --depth=1 --single-branch --branch main https://github.com/earendil-works/pi .; \
    git config user.email "build@localpibox.dev"; \
    git config user.name "LocalPibox Build"; \
    npm ci --ignore-scripts; \
    \
    # Patch files under /opt/pi-patches/*.patch are the single, preferred
    # patch mechanism. Fails loudly (no `|| true`) if a patch is present
    # but doesn't apply cleanly — a silently-skipped patch is worse than
    # a failed build.
    if ls /opt/pi-patches/pi-*.patch 1>/dev/null 2>&1; then \
        echo "=== Applying pi patches ==="; \
        for patch in /opt/pi-patches/pi-*.patch; do \
            echo "  Applying: $(basename "$patch")"; \
            git am "$patch"; \
        done; \
    else \
        echo "No pi-*.patch files found — building unpatched upstream pi"; \
    fi; \
    \
    npm run build; \
    mkdir -p /tmp/pi-packs; \
    for pkg in ai agent coding-agent tui; do \
      npm pack "./packages/$pkg" --pack-destination /tmp/pi-packs; \
    done; \
    npm install -g /tmp/pi-packs/*.tgz; \
    \
    # Smoke test — fail the build immediately if the installed binary
    # isn't actually functional, instead of finding out at container
    # runtime.
    /home/dev/.npm-global/bin/pi --version || (echo "FATAL: pi binary is not functional after install" && exit 1); \
    \
    ls -la /home/dev/.npm-global/bin/; \
    rm -rf /opt/pi-src/.git /opt/pi-src/src /opt/pi-src/test /opt/pi-src/tests /tmp/pi-packs

# ── Builder: Extensions + Config ───────────────────────────────────────────
USER root
RUN set -eux; \
    export PATH="/home/dev/.npm-global/bin:${PATH}"; \
    export HOME="/home/dev"; \
    \
    # ── Clone config repo — MUST be before `pi install`
    #    so settings.json exists for `pi install` to extend it. ───
    echo "=== Cloning config repo ==="; \
    mkdir -p /home/dev/.local/pi-config; \
    rm -rf /tmp/pi-config-repo; \
    git clone --depth=1 https://github.com/localpibox/config.git /tmp/pi-config-repo 2>&1 && \
    (cd /tmp/pi-config-repo && cp -r . /home/dev/.local/pi-config/) || echo "WARN: config clone failed"; \
    rm -rf /tmp/pi-config-repo; \
    \
    # ── Copy config files (baseline — pi install will extend settings.json) ──
    echo "=== Copying config ==="; \
    mkdir -p /home/dev/.pi/agent; \
    [ -f /home/dev/.local/pi-config/settings.json ] && cp /home/dev/.local/pi-config/settings.json /home/dev/.pi/agent/ || echo "WARN: no settings.json"; \
    [ -f /home/dev/.local/pi-config/mcp.json ] && cp /home/dev/.local/pi-config/mcp.json /home/dev/.pi/agent/ && sed -i 's/"directTools": true/"directTools": false/' /home/dev/.pi/agent/mcp.json || echo "WARN: no mcp.json"; \
    [ -f /home/dev/.local/pi-config/models.json ] && cp /home/dev/.local/pi-config/models.json /home/dev/.pi/agent/ || echo "WARN: no models.json"; \
    [ -f /home/dev/.local/pi-config/AGENTS.md ] && cp /home/dev/.local/pi-config/AGENTS.md /home/dev/.pi/agent/ || echo "WARN: no AGENTS.md"; \
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
    # ── Install extensions (now settings.json exists — each `pi install` extends it) ─
    echo "=== Installing extensions ==="; \
    # pi install clones to ~/.pi/agent/git/ and registers in settings.json
    pi install git:github.com/localpibox/lemonade-pi-plugin@patches/qwen-vision || echo "WARN: lemonade install failed"; \
    LEMONADE_DIR="/home/dev/.pi/agent/git/github.com/localpibox/lemonade-pi-plugin"; \
    if [ ! -d "$LEMONADE_DIR" ]; then \
        echo "WARN: lemonade checkout not found"; \
        find /home/dev/.pi -maxdepth 6 -iname 'lemonade-pi-plugin' -type d 2>/dev/null | head -5 || echo "  (not found)"; \
    elif [ -f /opt/pi-patches/lemonade-qwen-vision.patch ]; then \
        echo "=== Applying lemonade patches ==="; \
        cd "$LEMONADE_DIR"; \
        if git apply --check /opt/pi-patches/lemonade-qwen-vision.patch 2>/dev/null; then \
            git apply /opt/pi-patches/lemonade-qwen-vision.patch; \
            echo "  Applied lemonade-qwen-vision.patch"; \
        else \
            echo "  lemonade patch already applied or not applicable"; \
        fi; \
    fi; \
    pi install git:github.com/localpibox/pi-hermes-memory@fix/subprocess-provider || echo "WARN: memory install failed"; \
    # Global npm packages: use NPM_CONFIG_PREFIX to set install dir regardless of HOME
    NPM_CONFIG_PREFIX=/home/dev/.npm-global npm install -g pi-mcp-adapter || echo "WARN: pi-mcp-adapter install failed"; \
    NPM_CONFIG_PREFIX=/home/dev/.npm-global npm install -g @tintinweb/pi-subagents || echo "WARN: pi-subagents install failed"; \
    NPM_CONFIG_PREFIX=/home/dev/.npm-global npm install -g pi-powerline-footer || echo "WARN: pi-powerline-footer install failed"; \
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
    install_ext pi0 pi-vscode || echo "WARN: pi-vscode install failed"; \
    \
    chown -R 1000:1000 /home/dev/.pi /home/dev/.local /home/dev/.vscodium-server

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
    build-essential python3 libsqlite3-dev \
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

# ── Runtime: NOPASSWD sudo ──────────────────────────────────────────────────
# Containers run as non-root dev user (UID 1000). Scripts need sudo for apt-get
# (e.g. post-init native module rebuild). Without NOPASSWD, sudo prompts for a
# password and fails silently in the container entrypoint.
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/nopasswd && chmod 440 /etc/sudoers.d/nopasswd

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
COPY support/validate.sh /opt/devstack/validate.sh
COPY run.sh /usr/local/bin/run.sh
COPY stack.sh /usr/local/bin/stack.sh
COPY build-updates.sh /usr/local/bin/build-updates.sh
COPY load-updates.sh /usr/local/bin/load-updates.sh
# Symlink to PATH for easy shell access
RUN ln -sf /opt/devstack/start.sh /usr/local/bin/devstack-start \
    && ln -sf /opt/devstack/install-browser.sh /usr/local/bin/install-browser \
    && ln -sf /opt/devstack/validate.sh /usr/local/bin/validate-devstack
RUN chmod +x /opt/devstack/start.sh \
    /opt/devstack/install-browser.sh \
    /opt/devstack/validate.sh \
    /usr/local/bin/run.sh /usr/local/bin/stack.sh \
    /usr/local/bin/build-updates.sh /usr/local/bin/load-updates.sh

# ── Runtime: User ──────────────────────────────────────────────────────────
# Set ownership on copied directories. Dev user exists (created above).
RUN chown -R 1000:1000 /home/dev /opt/pi-patches \
    && chmod -R u+rwX /home/dev

# Create browser state directories (persisted via -v ~/.localpibox/agent-browser)
RUN mkdir -p /home/dev/.agent-browser/sessions \
    && chown -R 1000:1000 /home/dev/.agent-browser

USER dev
WORKDIR /home/dev/workspace

ENV PATH="/home/dev/.npm-global/bin:/home/dev/.local/bin:${PATH}"
ENV LPB_LEMONADE_BASE_URL="http://127.0.0.1:13305/v1"
ENV LPB_OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
ENV LPB_DEVCONTAINER_WORKSPACE_DIR="/home/dev/workspace"
ENV LPB_PI_SUPPORT_DIR="/opt/pi-support"

LABEL org.opencontainers.image.title="LocalPibox Devstack" \
      org.opencontainers.image.description="AI-powered dev environment with Pi coding agent" \
      org.opencontainers.image.source="https://github.com/localpibox/devstack" \
      org.opencontainers.image.vendor="LocalPibox" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["/opt/devstack/start.sh"]
