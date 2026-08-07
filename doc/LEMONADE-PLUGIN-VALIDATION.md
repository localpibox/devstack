# Lemonade Pi Plugin Validation

Validated: 2026-08-07

---

## Summary: ✅ Fully wired to llama.cpp backend

The lemonade-pi-plugin correctly registers Lemonade as a Pi provider and
configures Qwen models for the `qwen-chat-template` thinking format. The
plugin bridges Pi's `reasoning_effort` API to Lemonade/llama.cpp's
`chat_template_kwargs` protocol.

---

## Architecture

```
Pi CLI (extension)
  → registerProvider("lemonade", { api: "openai-completions", models: [...] })
  → /login: discovers servers via UDP beacon (13305) + HTTP fallback
  → fetchModels: GET /api/v1/models from Lemonade server
  → mapToProviderModel: configures each model with thinkingFormat, thinkingLevelMap, reasoningBudgetTokens
  → models-store.json: persists model config for subprocesses
  → /lemonade command: admin interface (status, models, load, pull, delete, refresh, discover)
```

---

## Key Functions

### 1. Discovery (lines 179-248)
- **UDP beacon**: Listens on port 13305 for Lemonade broadcasts (with SO_REUSEADDR/SO_REUSEPORT for coexistence with `lemonade scan`)
- **HTTP fallback**: Scans ports [13305, 8000, 1234, 9000, 8080]
- **Health check**: GET /api/v1/health with 3s timeout

### 2. OAuth Login (lines 433-513)
- Discovers servers → user picks one → collects optional API key → verifies health → registers provider
- Credentials stored as encoded OAuthCredentials (baseUrl, apiKey, serverName)
- refreshToken callback handles stale creds with env var fallback

### 3. Provider Registration (lines 397-430)
- Unregisters existing provider (idempotent)
- Registers with `api: "openai-completions"` (Pi's OpenAI-compatible API adapter)
- Includes OAuth block for credential refresh
- Headers include `Authorization: Bearer ${apiKey}` if provided

### 4. Model Mapping (lines 332-396) — THE BRIDGE TO LLAMA.CPP

```typescript
return {
  id: m.id,
  name: m.name || m.id,
  reasoning: reasoning || qwenReasoning,
  input,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow,
  maxTokens,
  compat: qwenReasoning
    ? {
        thinkingFormat: "qwen-chat-template",
        reasoningBudgetTokens: QWEN_REASONING_BUDGET_TOKENS,
        thinkingLevelMap: {
          off: null,
          minimal: "low",
          low: "low",
          medium: "medium",
          high: "high",
        },
      }
    : undefined,
  reasoningBudgetTokens: qwenReasoning ? QWEN_REASONING_BUDGET_TOKENS : undefined,
};
```

### 5. Qwen Model Detection (lines 313-331)

```
isQwenReasoningModel checks:
  1. /qwen3[._-]?\d/ — Qwen3.x family
  2. /qwq/ — QwQ reasoning models
  3. /qwen2\.5.*think/ — Qwen2.5-thinking
  4. /qwen2\.5-72b.*instruct/ — Qwen2.5-72B-Instruct (newer versions)
  5. llamacpp recipe + (mtp label or MTP name) — Qwen MTP models
```

### 6. syncModelStore (lines 837-890)
- Fetches models from Lemonade
- Persists to `~/.pi/agent/models-store.json`
- Enables subprocesses to resolve Lemonade models (prevents fallback to OpenRouter)

---

## End-to-End Flow: User requests thinking

```
User selects "high" thinking in Pi TUI
  ↓
Pi CLI sends: reasoningEffort: "high"
  ↓
openai-completions.ts (from pi fork):
  - detects thinkingFormat === "qwen-chat-template"
  - maps effort: model.thinkingLevelMap["high"] → "high"
  - builds chat_template_kwargs: {
      enable_thinking: true,
      preserve_thinking: true,
      reasoning_effort: "high"
    }
  - sets params.reasoning_budget_tokens = 0
  ↓
Lemonade /v1/chat/completions (OpenAI-compatible)
  ↓
Lemonade server (llama.cpp backend)
  - parses chat_template_kwargs
  - applies enable_thinking, reasoning_effort to Qwen's thinking protocol
  - passes reasoning_budget_tokens=0 to llama.cpp sampler
  - sampler soft-caps thinking tokens (bounded but non-zero)
  ↓
Response: thinking block + text output
  ↓
Pi parses thinking via qwen-chat-template thinking parser
  (not llama.cpp's reasoning parser, which has Qwen3 XML tag issues)
```

---

## Admin Interface (/lemonade)

| Command | What it does |
|---|---|
| `/lemonade status` | GET /api/v1/health — server version, loaded models, WebSocket port |
| `/lemonade models` | GET /api/v1/models — list with ●/○ loaded status, recipe, size |
| `/lemonade load <id>` | POST /api/v1/load — load model into memory |
| `/lemonade unload [id]` | POST /api/v1/unload — unload model (or all) |
| `/lemonade pull <id>` | POST /api/v1/pull — download model (may take a while) |
| `/lemonade delete <id>` | POST /api/v1/delete — remove from disk |
| `/lemonade refresh` | Re-fetch models, re-register provider |
| `/lemonade discover` | UDP beacon + HTTP port scan for visible servers |

---

## Critical Configuration Values

| Constant | Value | Purpose |
|---|---|---|
| `QWEN_REASONING_MAX_TOKENS_CONTEXT_RATIO` | `0.06` (6%) | Qwen: ~15.7k maxTokens on 262k window (leaves room for thinking) |
| `QWEN_REASONING_BUDGET_TOKENS` | `0` | Soft-capped thinking (bounded but non-zero) |
| `DEFAULT_MAX_TOKENS_CONTEXT_RATIO` | `0.06` (NOT 0.125) | ⚠️ **ISSUE**: Non-Qwen models also capped to 6% |
| `BEACON_PORT` | `13305` | UDP discovery |
| `HTTP_FALLBACK_PORTS` | `[13305, 8000, 1234, 9000, 8080]` | TCP fallback scan |

---

## Issues Found

### 1. ⚠️ DEFAULT_MAX_TOKENS_CONTEXT_RATIO is 0.06 (should be higher)

**Location:** Line 56
```typescript
const DEFAULT_MAX_TOKENS_CONTEXT_RATIO =
  parseFloat(process.env.MAX_TOKENS_CONTEXT_RATIO ?? '') > 0
    ? parseFloat(process.env.MAX_TOKENS_CONTEXT_RATIO!)
    : 0.06;  // ← Too low for non-reasoning models
```

**Problem:** The default is `0.06` (6% of context window), which is appropriate
for Qwen reasoning models but too conservative for other models. On a 128k
context window, this gives only 7,680 maxTokens for ALL models — including
non-reasoning models that don't need thinking blocks reserved.

**Expected:** Qwen models should use `0.06`; other models should use something
like `0.125` (12.5%) or `0.15` (15%).

**Impact:** Non-Qwen models running through Lemonade get unnecessarily limited
max output tokens.

**Suggestion:** Change `DEFAULT_MAX_TOKENS_CONTEXT_RATIO` to `0.125` (or use
`process.env` default) and apply the `0.06` ratio only when `isQwenReasoningModel(m)` is true.

### 2. ⚠️ Duplicate `isQwenReasoningModel` definition

**Location:** Line 313 (function) + Line 846 (inline arrow function in syncModelStore)

**Problem:** `syncModelStore` redefines `isQwenReasoningModel` as a local arrow
function with different logic (only checks `qwen3`, `qwen-3`, `qwq` — doesn't
check Qwen2.5 variants or MTP models).

**Impact:** syncModelStore may produce a different model list than the runtime
provider registration. This could cause subprocesses to see different models
than what Pi sees at runtime.

**Suggestion:** Extract the shared logic into a utility function or call the
same `isQwenReasoningModel` function used by `mapToProviderModel`.

### 3. ℹ️ syncModelStore inline type safety

**Location:** Line 857-863

**Problem:** The inline definition of `isQwenReasoningModel` in syncModelStore
uses simplified detection (missing Qwen2.5, MTP variants). Also uses `as any`
for `max_context_window` access, while `mapToProviderModel` handles the same
field via multiple fallback paths.

**Impact:** Potential inconsistency in maxTokens calculation between runtime
and subprocess models.

---

## Build Verification

**TypeScript config:** ✅ Proper — ES2022 target, strict mode, bundler resolution,
type-only includes (no runtime node_modules needed).

**Extension entry:** ✅ `extensions/index.ts` via `pi.extensions` in package.json.

**No build step needed:** ✅ Pi loads `.ts` directly via jiti — the plugin is a
single file extension, no compilation required.

---

## Test Coverage

No formal test suite found in the repo. The plugin relies on:
- Runtime validation (health checks with timeouts)
- User-facing admin commands (`/lemonade`)
- Process.env for configuration overrides

**Recommendation:** Add unit tests for `mapToProviderModel` covering:
- Qwen3.x → qwen-chat-template + thinkingLevelMap + reasoningBudgetTokens=0
- Qwen2.5-thinking → qwen-chat-template + thinkingLevelMap + reasoningBudgetTokens=0
- Non-Qwen → no compat override
- Vision models → input includes "image"

---

## Conclusion

The plugin is **correctly wired to llama.cpp** via the `qwen-chat-template`
thinking format. The key wiring:

1. Pi sends `chat_template_kwargs` with `enable_thinking`, `reasoning_effort`, `preserve_thinking`
2. Lemonade passes these through to llama.cpp's Qwen template handler
3. `reasoning_budget_tokens=0` is sent as a top-level param (llama.cpp sampler handles soft-cap)
4. Pi handles thinking token extraction (not llama.cpp's parser, which has Qwen3 XML issues)

Two issues found:
1. **DEFAULT_MAX_TOKENS_CONTEXT_RATIO too low** (0.06 affects ALL models, not just Qwen)
2. **Duplicate isQwenReasoningModel** in syncModelStore with different detection logic

These are configuration/logic issues, not wiring issues. The communication
between Pi → Lemonade → llama.cpp is correct.
