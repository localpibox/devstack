# Repository Organization — Final Plan

## 4 Repositories

```
github.com/localpibox/
├── pi                             # Forked monorepo + reasoning_effort patch
├── lemonade-pi-plugin             # Forked + patched (Qwen detection)
├── config                         # Settings + scripts for Pi setup
└── devstack                       # Docker-compose + Dockerfile for reproducible stack
```

---

## 1. `pi` — Full Monorepo Fork (patched)

**Source:** `earendil-works/pi`  
**Target:** `localpibox/pi`

### What it is
Exact copy of the upstream monorepo with a local patch applied to `packages/ai/`.

### Patch
File: `packages/ai/dist/api/openai-completions.js`

```javascript
// Around line 571 — Qwen branch
else if (compat.thinkingFormat === "qwen" && model.reasoning) {
    params.enable_thinking = !!options?.reasoningEffort;
    // Also send reasoning_effort for granularity (high/medium/low)
    if (options?.reasoningEffort && options.reasoningEffort !== "off") {
        params.reasoning_effort = model.thinkingLevelMap?.[options.reasoningEffort] ?? options.reasoningEffort;
    }
}
```

Same for `qwen-chat-template` branch (around line 575-579).

### Why fork the full monorepo
- Patch is in `packages/ai/` — part of the monorepo
- Easier to stay in sync with upstream (merge future changes)
- Can submit PRs to upstream if patch is generally useful
- Can add other customizations later without restructuring
- Pi's `git:` dependency handles workspace resolution automatically

### Versioning
- Follow upstream versioning (e.g., `0.82.1`)
- Add local suffix: `0.82.1+localpibox.1`
- Or bump patch on each local change: `0.82.2`, `0.82.3`, etc.

### CI
- `action.yml`: Run `npm run build` (workspace), `npm test`
- Only run on `packages/ai` changes + main pushes

### Upstream contribution path
When the patch matures:
1. Test it works broadly
2. Submit a PR to `earendil-works/pi`
3. If merged, remove our fork (or keep for other local customizations)

---

## 2. `lemonade-pi-plugin` — Forked + Patched

**Source:** `cfxdevkit/lemonade-pi-plugin` (already forked locally)  
**Target:** `localpibox/lemonade-pi-plugin`

### What it does
Registers Lemonade as a Pi provider. The patch adds Qwen reasoning model detection so Pi allows thinking level changes.

### Commits already done
```
6c06def feat: detect Qwen reasoning models for enable_thinking support
```

### Versioning
- Start at `0.82.1` (current upstream version)
- Bump minor on feature additions, patch on bugfixes

### CI
- `action.yml`: TypeScript type check + build on push/PR

---

## 3. `config` — Configuration Repo

**Purpose:** Complete Pi configuration for reproducible setup  
**Contains:**
```
config/
├── settings.json      # Full settings (providers, models, thinking)
├── mcp.json           # MCP server config
├── auth.json.example  # Auth template (no real keys)
├── AGENTS.md          # Global agent instructions
├── install.sh         # One-command setup script
└── README.md          # Setup instructions
```

### `settings.json`
```json
{
  "packages": [
    "git:github.com/localpibox/pi@main",
    "git:github.com/localpibox/lemonade-pi-plugin@main",
    "npm:pi-hermes-memory",
    "npm:pi-mcp-adapter",
    "npm:@tintinweb/pi-subagents",
    "npm:pi-powerline-footer"
  ],
  "defaultProvider": "lemonade",
  "defaultModel": "Qwen3.6-35B-A3B-MTP-GGUF",
  "defaultThinkingLevel": "high",
  "mcp": { "directTools": true, "toolPrefix": "server" }
}
```

### `install.sh`
```bash
#!/bin/bash
# Clone and configure localpibox Pi stack
# Usage: curl -sL <url>/install.sh | bash
```

### CI
- No CI needed (config repo)

---

## 4. `devstack` — Docker Stack

**Purpose:** Reproducible containerized dev environment  
**Contains:**
```
devstack/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── devstack.sh
└── README.md
```

### Key changes from current workspace
- Point `pi install` to `git:github.com/localpibox/pi@main`
- Point to `git:github.com/localpibox/lemonade-pi-plugin@main`
- Pre-install the full stack in one command

### CI
- `action.yml`: Build Docker image + verify it works

---

## Installation Flow

After setup, `~/.pi/agent/settings.json`:
```json
{
  "packages": [
    "git:github.com/localpibox/pi@main",
    "git:github.com/localpibox/lemonade-pi-plugin@main",
    ...
  ]
}
```

## Creation Order

1. **`pi`** — fork full monorepo, apply reasoning_effort patch
2. **`lemonade-pi-plugin`** — push local fork (`6c06def`) to new repo
3. **`config`** — settings + install script
4. **`devstack`** — docker-compose + Dockerfile

## After Creation

1. Update `~/.pi/agent/settings.json` to point to `localpibox/*` repos
2. Update Dockerfile URL
3. Push everything
4. Clean up old `cfxdevkit/` references
5. Document the setup

## Upstream Contribution Strategy

- Keep fork history clean with squashed local commits
- Tag releases that should be considered for upstream
- Open PRs against `earendil-works/pi` for generally useful changes
- Keep local-only customizations in separate branches
