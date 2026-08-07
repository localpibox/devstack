# Qwen3 + llama.cpp Thinking Overflow — Research & Best Practices

## Problem Statement

Qwen3.6-35B-A3B on llama.cpp backend via Lemonade throws:
> "the request exceeds the available context size, try increasing it"

This error comes from `OVERFLOW_PATTERNS` in `pi-ai` matching `/exceeds the available context size/i` (llama.cpp server).

---

## Root Cause

The error is **not** from the model filling all context with thinking. It's a **request sizing issue** where `prompt + max_tokens` exceeds the model's context window.

### The Three-Layer Problem

1. **Lemonade extension sets `maxTokens = contextWindow * 0.125`** (~32k for 262k window)
   - This is the *default* max tokens ratio
   - 30k is sent on every request

2. **Pi harness compaction triggers at `contextWindow - reserveTokens`**
   - Default: `262,144 - 16,384 = 245,760` (93.8% of window)
   - Compaction generates a summary request that includes: summary text + retained messages + ALL thinking blocks from prior turns

3. **Thinking blocks are HUGE** — Qwen models generate 10-20k tokens of reasoning per turn
   - When thinking is enabled, retained history includes these blocks
   - They count toward `usage.input` (prompt tokens)
   - They also consume `usage.output` (output tokens)

### Why 262k context / 30k maxTokens Still Overflows

The compaction request adds:
- Summary text (~500-2000 tokens)
- Retained tail (includes ALL thinking blocks from recent turns)
- System prompt + config

Even with compaction at 93.8%, the new request can still exceed the hard limit because the thinking blocks make the prompt grow turn-by-turn faster than compaction can trim.

---

## Evidence from Upstream Research

### Qwen Code PR #6556 (QwenLM/qwen-code) — "Clamp max_tokens to context window"

This PR from the Qwen Code team identified the same root cause:

> **The client injects a large output request (`max_tokens`) on every turn** — a default that escalates toward 64K — and then has to defend the window against its own injection.
>
> To guarantee `prompt + output ≤ window`, the code subtracts that reserved output budget from the window *before* computing the compaction thresholds. On a 200K window with a 64K reservation, compaction was effectively planning around a 136K window.

**Their fix:**
1. **Remove the output reservation** — size each request to fit the room left in the window
2. **Move compaction threshold from 70% to 85%** (compaction fires closer to the limit)
3. **Clamp `max_tokens` per request** to `min(model.maxTokens, window - current_prompt - safety_margin)`
4. **Flat 64K ceiling** on output requests

### llama.cpp Issues

1. **DeepSeek vs Qwen reasoning parser** (`reasoning_format`)
   - llama.cpp's default parser was designed for DeepSeek's field-based format
   - Qwen uses inline `<thinking>` XML tags
   - The parser splits on `</think>` but breaks on Qwen's structural format
   - Fix: `--reasoning-format none` + client-side tag extraction

2. **KV cache checkpoint bugs for hybrid models** (DeltaNet/Mamba)
   - Qwen3.5/3.6 use Gated DeltaNet hybrid architecture
   - Checkpoint search uses `pos_min < pos_min_thold` but `pos_min` always equals full sequence length for recurrent models
   - Fix was merged in llama.cpp commits 5ee146d, 1f888, 90906fc

3. **Chat template emits empty thinking blocks** (QwenLM/Qwen3.6#131)
   - When thinking is not preserved, the last assistant turn breaks KV cache reuse
   - Qwen3.6 added `preserve_thinking` flag to keep thinking blocks everywhere
   - Without it, prefix mismatches cause full prompt re-processing on every turn

4. **Qwen3-Thinking needs `max_tokens >= ~300`** (llama.cpp#20931)
   - The thinking block alone uses 200-400 tokens
   - If `max_tokens < ~300`, the model exhausts the limit during thinking and produces no visible answer

### Qwen3.6 Context Quality Degradation

Research shows Qwen3.6-27B gets measurably less smart as context fills up:
- **Stable region (0-40% of max context):** consistent performance
- **Critical transition (40-50%):** performance collapses 45%+
- **Degraded region (50-95%):** stays low, no recovery

This is a fundamental property of DeltaNet's gating mechanism — not a bug.

---

## Current Pi/lemonade-pi-plugin Config Issues

### What the lemonade extension does

```typescript
// extensions/index.ts — mapToProviderModel()
const contextWindow = cfg["context_window"] ?? 128000;
const maxTokens = Math.floor(contextWindow * 0.125); // = 32,768 for 262k

// For Qwen reasoning models:
compat: { thinkingFormat: "qwen-chat-template" }
```

This sets `maxTokens = 32k` which gets sent to the model on every request.

### What Pi does on each request

The Pi harness takes `model.maxTokens` (32k) and sends `max_tokens: 32768` on every request. Combined with a context that's already grown to ~230k tokens (from accumulated thinking + messages), the total is:

```
prompt (230k) + max_tokens (32k) = 262k → hits the exact limit
```

When thinking blocks from compaction are added to the prompt, it exceeds.

### The 0.125 ratio is too high for thinking models

With thinking enabled, Qwen models consume tokens in two ways:
- **Input tokens** (prompt): system + history + thinking blocks
- **Output tokens** (response): thinking block (10-20k) + answer (1-5k)

A 0.125 ratio (32k maxTokens) means the model has 32k tokens of "output budget." But thinking consumes ~20k of that budget, leaving only ~12k for actual output. The model either cuts off mid-thought or fills the budget with thinking.

---

## Recommended Fixes

### Fix 1: Reduce `max_tokens` for thinking models

The `maxTokens` in the model mapping should be much lower for Qwen thinking models:

```
Current: maxTokens = 262,144 * 0.125 = 32,768
Proposed: maxTokens = 16,384 (for thinking Qwen models)
```

This leaves more room for thinking blocks while ensuring the total stays under the window.

### Fix 2: Soft-cap thinking for compaction

**Important:** Qwen models cannot have thinking fully disabled. The correct approach is two-fold:

1. **Omit the `reasoning` field during compaction** — sets `enable_thinking=false` for Qwen → bounded (soft-capped) thinking phase
2. **`reasoningBudgetTokens: 0` in the lemonade plugin** — provides the actual soft-cap that limits thinking length

The lemonade plugin already sets `reasoningBudgetTokens: 0` via `compat.thinkingFormat: "qwen-chat-template"`. The Pi fork omits `reasoning` during compaction so Qwen receives `enable_thinking=false` → soft-capped thinking.

Combined, these prevent runaway meta-thinking during summary generation while still allowing the model to reason about what to summarize.

### Fix 3: Increase reserveTokens for thinking models

Current: `reserveTokens = 16,384`
Proposed: `reserveTokens = 32,768`

This triggers compaction earlier (at `262,144 - 32,768 = 229,376` = 87.5%), leaving more room for the compaction request itself.

### Fix 4: Per-request output clamping (upstream pattern)

Following Qwen Code's approach, clamp `max_tokens` on every request:
```
max_tokens = min(model.maxTokens, contextWindow - current_prompt - safety_margin)
```

This is the most robust fix but requires changes to Pi's request sending path.

### Fix 5: Lemonade extension should not set high maxTokens

The 0.125 ratio should be much lower for thinking models. A better approach:

```typescript
// For Qwen reasoning models
maxTokens = Math.floor(contextWindow * 0.06); // = 15,728 for 262k window
// Or even lower: maxTokens = 16,384 (compaction reserveTokens)
```

This ensures `prompt + max_tokens` fits comfortably within the window even with thinking blocks.

---

## Best Practices Summary

| Practice | Why | Impact |
|---|---|---|
| **Soft-cap thinking for compaction** | Qwen can't be disabled; soft-cap via `reasoningBudgetTokens:0` + omit reasoning | High |
| **Reduce maxTokens for thinking models** | Leaves room for thinking blocks | High |
| **Increase reserveTokens** | Compaction fires earlier | Medium |
| **Per-request output clamping** | Guarantees prompt + output ≤ window | High (upstream pattern) |
| **Use `--reasoning-format none` on llama.cpp** | Avoids parser corruption | Medium |
| **Enable `preserve_thinking` in chat template** | Better KV cache, consistent reasoning | Medium |
| **Lower context usage to 85% threshold** | Compaction fires before degradation zone | Medium |
| **Use `thinking_budget` to cap thinking tokens** | Qwen API supports this | Medium |

---

## References

- [Qwen3 Thinking Disable Reality](../doc/QWEN-THINKING-DISABLE.md) — Qwen cannot be fully disabled; only soft-capped via `reasoningBudgetTokens:0`
- [Qwen Code PR #6556 — clamp max_tokens to context window](https://github.com/QwenLM/qwen-code/pull/6556)
- [llama.cpp reasoning parser vs Qwen3](https://blog.gopenai.com/the-only-correct-way-to-use-llama-cpp-with-qwen3-6-27b-d550bd0605a7)
- [Qwen3-Thinking max_tokens < 300](https://github.com/ggml-org/llama.cpp/discussions/20931)
- [Qwen3.6 KV cache checkpoint bugs](https://github.com/ggml-org/llama.cpp/issues/22384)
- [Qwen3.6 chat template thinking blocks](https://github.com/QwenLM/Qwen3.6/issues/131)
- [Qwen3.6 context degradation research](https://blog.gopenai.com/why-llm-gets-dumber-as-context-grows-00bc19e36548)
- [Qwen thinking docs — `thinking_budget`](https://docs.qwencloud.com/developer-guides/text-generation/thinking)
- [Qwen3.6 `preserve_thinking` flag](https://huggingface.co/Qwen/Qwen3.6-35B-A3B#preserve-thinking)

---

## Fork Cleanup Plan

The current lemonade-pi-plugin has several issues that should be cleaned up:

1. **Remove `reasoning_effort` from the model mapping** — llama.cpp backend doesn't respect it (confirmed in plugin code comments)
2. **Lower `maxTokens` for Qwen reasoning models** — set to 16k instead of 32k
3. **Keep `thinkingFormat: "qwen-chat-template"`** — this is correct for Pi to send the right parameters
4. **Consider adding `thinking_budget` support** — Qwen API supports this to cap thinking tokens
5. **Remove the `compat.thinkingFormat` hack** if Pi's Qwen patch is upstreamed
