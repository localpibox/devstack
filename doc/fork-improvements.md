# LocalPibox Fork Improvements

> Generated: 2025-08-13  
> Status: Complete — Qwen3.6 reasoning + vision fully operational

---

## Architecture

This stack uses 6 repositories. The two code forks and their changes:

| Repo | Upstream | Purpose |
|---|---|---|
| `lpb-stack/pi` | `earendil-works/pi` | Forked Pi monorepo — Qwen reasoning protocol + overflow detection |
| `lpb-stack/lemonade-pi-plugin` | `lemonade-sdk/lemonade-pi-plugin` | Lemonade provider — Qwen model detection, vision, dynamic sizing |
| `lpb-stack/pi-subagents` | `tintinweb/pi-subagents` | Subagent model registry — removes Anthropic defaults, local-first |
| `lpb-stack/config` | — | User settings, skills, agents |
| `lpb-stack/devstack` | — | Docker-based dev environment |
| `lpb-stack/lpb-memory` | — | Persistent memory extension |

---

## Pi Fork (`lpb-stack/pi`)

**Key commit: `53c1dc2` — surgical Qwen patches on v0.84.1**

This commit makes the **surgical edits** to Pi itself that enable the Qwen reasoning protocol:

| File | Change | Purpose |
|---|---|---|
| `packages/ai/src/api/openai-completions.ts` | Adds `reasoning_effort` mapping to `chat_template_kwargs` | Sends `reasoning_effort: "high"|"medium"|"low"` to Qwen models when thinking is enabled |
| `packages/ai/src/api/openai-completions.ts` | Adds `reasoning_budget_tokens` param | Sends soft-cap (0) to prevent runaway thinking blocks that exhaust max_tokens |
| `packages/ai/src/types.ts` | Adds `reasoningBudgetTokens` compat field | New compat flag for Qwen reasoning budget |
| `packages/ai/src/utils/overflow.ts` | Adds **Case 4** reasoning overflow detection | Detects when Qwen thinking blocks silently consume output token budget (input ≥ 90% of context, stopReason=withLength, output > 0, no text/tool calls) |
| `packages/coding-agent/src/config.ts` | Adds `LOCALPIB_VERSION` env | Reads from `LPB_VERSION` env for fork identification |
| `VERSION` | New file: `0.0.1-lpb` | Fork version marker |
| `package.json` | Version → `0.0.1-lpb` | Fork version |

**Additional 3 commits on top (lpb-dev branch):**

| Commit | Description |
|---|---|
| `2a3e9bc` feat | `allowScripts` for native addons |
| `346947d` hooks | Validation-only hook sync for devstack |
| `8449290` chore | Install husky pre-commit hook |

**Verdict:** `53c1dc2` is the **critical commit** — it wires Pi's OpenAI completions layer to send Qwen-specific reasoning parameters (`reasoning_effort`, `reasoning_budget_tokens`) and adds overflow detection for thinking-block exhaustion.

---

## Subagents Fork (`lpb-stack/pi-subagents`)

**Key commit: `5a3159d` — centralized model registry on upstream v0.15.0**

This commit **removes Anthropic-hardcoded defaults** from the subagents extension, making it fully local-first:

| File | Change | Purpose |
|---|---|---|
| `src/agent-runner.ts` | Adds `globalDefaultModel` setting + getter/setter | New centralized model registry — single source of truth for all subagent models |
| `src/agent-runner.ts` | `resolveDefaultModel()` priority: explicit > config > **globalDefaultModel** > parent | New intermediate step between config and parent inheritance |
| `src/default-agents.ts` | Removes `model: "anthropic/claude-haiku-4-5"` from Explore agent | `model: undefined` — inherits parent model |
| `src/index.ts` | Reads `globalDefaultModel` from settings + resolves it | Applies the centralized model to agent spawns |
| `src/settings.ts` | Adds `globalDefaultModel` field to settings interface | Configurable via `pi-defaults.json` or `/agents → Settings` |
| `package.json` | Version → `0.14.3` (reverted from 0.15.0) | Aligns with upstream stable release |
| `README.md` | Rewritten — adds "Configuring for local models" section | Documents `globalDefaultModel: null` in `pi-defaults.json` |

**Why it matters:** Without this change, subagents would default to `anthropic/claude-haiku-4-5` and **fail when no Anthropic API key is configured**. For stacks running entirely on local models (like LocalPibox), this is critical.

**Model resolution chain (after patch):**
1. Explicit `model` param in `Agent()` call
2. `model` field in agent `.md` frontmatter
3. **`globalDefaultModel`** from `pi-defaults.json` / `subagents.json` (centralized registry)
4. Parent session model (inherit)

**Configuration for local-first:**
```json
{
  "extensions": {
    "@tintinweb/pi-subagents": {
      "globalDefaultModel": null,
      "disableDefaultAgents": true
    }
  }
}
```
`globalDefaultModel: null` means subagents inherit whatever model the parent session uses — **zero Anthropic dependency**.

**Verdict:** This is the **glue that makes the local-only stack work end-to-end** — it ensures subagents (like `vision-analysis`, `researcher`, etc.) all use the session's local Qwen model instead of falling back to Anthropic.

---

## Lemonade Fork (`lpb-stack/lemonade-pi-plugin`)

**Changes: +334 lines across 13 files — all major improvements**

### 1. Qwen Reasoning Model Support

**File:** `lib/models.ts` (~130 new lines)

| Feature | Implementation |
|---|---|
| **Qwen detection** | `isQwenReasoningModel()` — detects Qwen3.x, QwQ, Qwen2.5-thinking, Qwen2.5-72B via regex on name/recipe |
| **MTP detection** | `isMtpModel()` — detects Multi-Token Prediction models via name, recipe, or `mtp-gguf` label |
| **FLM detection** | `flmTemplateRejectsDeveloperRole()` — disables reasoning for FLM backends (reject `developer` role in chat template) |
| **Dynamic maxTokens ratio** | Reasoning models: `0.06 × contextWindow` (~15.7k for 262k). Non-reasoning: `0.125` (~32k) — prevents context overflow from thinking blocks |
| **Thinking protocol** | Adds `enable_thinking`, `reasoning_budget_tokens`, `thinkingFormat: "qwen-chat-template"` to Qwen models |
| **Heuristic detection** | `isReasoningByHeuristic()` — catches models where `recipe` field is absent or non-matching (checks name, labels) |
| **Reasoning flag** | Combines `isReasoningModel(recipe)` + heuristic + Qwen detection |

### 2. Vision Capability Detection

**File:** `lib/models.ts`

| Feature | Implementation |
|---|---|
| **Label-based detection** | `detectVision()` — checks for `"vision"` in model labels |
| **Auto image input** | Vision models automatically get `input: ["text", "image"]` |

### 3. Sync Model Store

**File:** `lib/sync-store.ts` (new, 61 lines)

| Aspect | Details |
|---|---|
| **Purpose** | Keeps `~/.pi/agent/models-store.json` in sync with Lemonade API |
| **Why** | Subprocesses and subagents resolve models with correct `contextWindow` and `maxTokens` without network calls |
| **Triggers** | OAuth login, token refresh, `/lemonade refresh`, `/lemonade change-ctx` |
| **Error handling** | Non-critical — falls back to provider at runtime if sync fails |

### 4. API Field Propagation

**File:** `lib/http.ts` (+8 lines)

| Field | Purpose |
|---|---|
| `labels` | Passed through to drive `detectVision()` and other heuristics |
| `config` | Passed through for backend configuration |
| `max_context_window` | Respected for context sizing |

### 5. Auth & Config Improvements

**Files:** `extensions/index.ts`, `lib/provider.ts`

| Change | Details |
|---|---|
| `auth_type: "api-key"` | Registers provider as API-key auth type |
| Spread copy in `refreshToken` | `{ ...decodeCreds(creds) }` — prevents credential mutation |
| `creds.access` fallback | `getApiKey` checks `creds.access` as fallback |
| `LEMONADE_BASE_URL` env fallback | Resolves baseUrl when stored creds are stale |

### 6. Admin Command & OAuth Sync

**Files:** `lib/admin.ts`, `lib/oauth.ts`

| Change | Details |
|---|---|
| Post-refresh sync | `syncModelStore()` after `/lemonade refresh` |
| Post-change-ctx sync | `syncModelStore()` after `/lemonade change-ctx` |
| Post-login sync | `syncModelStore()` after OAuth login |
| Post-refresh sync | `syncModelStore()` in `registerLemonadeProvider` |

### 7. Qwen Constants

**File:** `lib/constants.ts` (21 new lines)

| Constant | Value | Purpose |
|---|---|---|
| `DEFAULT_MAX_TOKENS_CONTEXT_RATIO` | 0.125 | Non-reasoning Qwen models |
| `QWEN_REASONING_MAX_TOKENS_CONTEXT_RATIO` | 0.06 | Reasoning models (thinking headroom) |
| `QWEN_REASONING_BUDGET_TOKENS` | 0 | Soft-capped thinking (prevents runaway) |

### 8. Model Type Definitions

**File:** `lib/types.ts`

| Change | Details |
|---|---|
| `labels?: string[]` | Added to `LemonadeModelInfo` interface |

### 9. Documentation & Version

| File | Purpose |
|---|---|
| `CONTRIBUTING.md` | Docs on patch model, rebase workflow, forking guide |
| `VERSION` | `0.2.0-lpb` — fork version marker |

---

## Key Design Decisions

### Patch Model

All LocalPibox changes are kept as a **single squashed commit** on top of upstream `main`. The delta is always one clean patch.

```
upstream main ──→ [latest] ──┐
                             │
lpb-dev branch      ──→ [lpb patch]──┘
```

To update:
```bash
git fetch upstream main
git checkout lpb-dev
git rebase upstream/main
git push --force-with-lease origin lpb-dev
```

### Why the Ratios Matter

| Model Type | Ratio | 262k Context → maxTokens | Why |
|---|---|---|---|
| Reasoning (Qwen MTP) | 0.06 | ~15.7k | Thinking blocks consume 10-20k tokens; leaving budget prevents context overflow |
| Non-reasoning (Qwen) | 0.125 | ~32k | Standard ratio, no thinking overhead |

### FLM vs MTP Backend

| Backend | Reasoning Support | Why |
|---|---|---|
| **MTP** (`Qwen3.6-35B-A3B-MTP-GGUF`) | ✅ Yes | Uses newer chat template that accepts `developer` role |
| **FLM** (`qwen3.5-9b-FLM`, `qwen3.6-moe-35b-a3b-FLM`) | ❌ No | Chat template only accepts `system/user/assistant/tool` roles, raises error on `developer` |

---

## Vision Pipeline

### Custom Agent (`vision-analysis`)

Created at `~/.pi/agent/agents/vision-analysis.md`

**Workflow:**
1. `mcp` → `agent-browser_open` — open URL in Chrome
2. `mcp` → `agent-browser_screenshot` — capture screenshot
3. `read` — pass image to session model for vision analysis
4. `mcp` → `agent-browser_close` — close browser

**Usage:**
```bash
Agent(description: "Vision analysis of <url>", subagent_type: "vision-analysis", prompt: "Analyze this page: <url>")
```

Runs in background, uses session model by default (can override with `model:` parameter).

### Manual Alternative

```bash
# Open browser
mcp({ tool: "agent-browser_open", args: { url: "..." } })
# Take screenshot
mcp({ tool: "agent-browser_screenshot", args: {} })
# Read image (passes to session model)
read(path: "/home/lpb/.agent-browser/tmp/screenshots/screenshot-xxx.png")
# Close browser
mcp({ tool: "agent-browser_close", args: { all: false } })
```

---

## Known Issues & Mitigations

### Qwen3 Thinking Overflow (2026-08-02)

Qwen3.6 with thinking enabled throws "context size exceeded" when `prompt + max_tokens` exceeds the 262k window.

**Mitigations:**
- `maxTokens` reduced to ~15k (`ratio 0.06`) — leaves room for 10-20k thinking blocks
- `reserveTokens` doubled to 32k — compaction fires at ~88% (230k) instead of ~94% (246k)
- Thinking disabled during compaction — prevents meta-thinking waste
- `LPB_MAX_TOKENS_CONTEXT_RATIO=0.06` set in `support/start.sh` and `.env.example`

### agent-browser_chat

Requires `AI_GATEWAY_API_KEY` (Vercel AI SDK gateway). Not configurable per-call. Cannot point at local Lemonade server. Not usable with this stack.

---

## Quick Reference

### Environment Variables

| Variable | Value | Purpose |
|---|---|---|
| `LEMONADE_BASE_URL` | `http://127.0.0.1:13305/v1` | Model API endpoint |
| `VISION_MODEL` | `Qwen3.6-35B-A3B-MTP-GGUF` | Vision model ID |
| `LPB_MAX_TOKENS_CONTEXT_RATIO` | `0.06` | Max tokens ratio for Qwen reasoning |
| `AGENT_BROWSER_MAX_OUTPUT` | `4000` | Max chars for snapshot output |

### Admin Commands

| Command | Purpose |
|---|---|
| `/lemonade health` | Check server health |
| `/lemonade models` | List detected models |
| `/lemonade refresh` | Re-sync models |
| `/lemonade change-ctx` | Change context window for active model |

### Support Files

| Path | Purpose |
|---|---|
| `/opt/pi-support/bin/session-uuid` | Generate unique session IDs |
| `/opt/pi-support/bin/browser-state-cleanup` | Cleanup browser state volumes |
| `/opt/pi-support/browser-validate.ts` | Browser validation entry point |
| `/opt/pi-support/start.sh` | Start script |
| `/opt/pi-support/config/agent-browser-action-policy.json` | Agent action policies |
