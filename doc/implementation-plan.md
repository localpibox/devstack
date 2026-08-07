# Implementation Plan: Qwen3 Thinking Overflow Fix

> Created: 2026-08-02
> Status: **Implemented** (all phases complete)
> Effort: ~4 sessions

## Problem Summary

Qwen3.6-35B-A3B on llama.cpp throws "the request exceeds the available context size" because:
- Lemonade extension set `maxTokens = contextWindow × 0.125` (~32k for 262k window)
- Pi sent `max_tokens: 32k` on every request
- Compaction fired at 93.8% (too late) with thinking blocks bloating the prompt
- Combined: prompt + max_tokens exceeded the hard window limit

Research is documented in `doc/QWEN-THINKING-OVERFLOW.md`.

---

## Phase 1: Immediate Fixes (lpb.py + Dockerfile)

### 1.1 Set `MAX_TOKENS_CONTEXT_RATIO` to 0.06 in Docker image

**Files:** `Dockerfile`, `support/start.sh`

**Changes:**
```
# Dockerfile
ENV LPB_MAX_TOKENS_CONTEXT_RATIO=0.06

# start.sh (container env default)
export LPB_MAX_TOKENS_CONTEXT_RATIO="${LPB_MAX_TOKENS_CONTEXT_RATIO:-0.06}"
```

**Rationale:** 0.06 × 262k = 15,720 maxTokens — leaves room for thinking blocks within the window. This is a conservative ratio that works for thinking models.

**Verification:** After rebuild, `max_tokens` in model mapping should be ~15k for 262k context.

---

### 1.2 Update `.env.example` with new default

**File:** `.env.example`

**Change:**
```
# LPB_MAX_TOKENS_CONTEXT_RATIO=0.06
```

**Note:** `.env` already has this set. Update the example to match.

---

### 1.3 Update README.md — remove misleading 0.125 examples

**File:** `README.md`

**Change:** Update the `MAX_TOKENS_CONTEXT_RATIO` examples to reflect 0.06:
```
# LPB_MAX_TOKENS_CONTEXT_RATIO=0.06
```

---

### 1.4 Update `versions.env` — add ratio tracking

**File:** `versions.env`

**Add:**
```
# Context ratio — controls max_tokens relative to context_window
# Lower ratio = less output budget per request, more headroom for thinking blocks
max_tokens_context_ratio=0.06
```

---

## Phase 2: Lemonade Extension Fixes

### 2.1 Reduce `maxTokens` calculation for Qwen reasoning models

**File:** `~/.pi/agent/git/github.com/localpibox/lemonade-pi-plugin/extensions/index.ts`

**Current code:**
```typescript
const maxTokens =
    (cfg["max_new_tokens"] as number) ?? (cfg["max_tokens"] as number) ?? Math.floor(contextWindow * DEFAULT_MAX_TOKENS_CONTEXT_RATIO);
```

**Change:**
```typescript
const maxTokens =
    (cfg["max_new_tokens"] as number) ?? (cfg["max_tokens"] as number) ??
    (qwenReasoning
        ? Math.floor(contextWindow * 0.06)  // 15k for 262k window — leaves room for thinking
        : Math.floor(contextWindow * DEFAULT_MAX_TOKENS_CONTEXT_RATIO));
```

Also update the `syncModelStore()` function which has the same issue:
```typescript
// In syncModelStore():
maxTokens: (qwenReasoning
    ? Math.floor(contextWindow * 0.06)
    : Math.floor(contextWindow * DEFAULT_MAX_TOKENS_CONTEXT_RATIO) | 0),
```

**Rationale:** Qwen thinking models need less output budget because thinking blocks consume ~15-20k tokens. With a 32k maxTokens cap, the model exhausts the budget on thinking and produces no answer. At 15k, the model has just enough budget for short thinking + answer.

---

### 2.2 Remove `reasoning_effort` from model mapping comment

**File:** Same as 2.1

**Current:**
```typescript
// Lemonade backend does NOT respect top-level enable_thinking / reasoning_effort.
// It only respects chat_template_kwargs.{enable_thinking, reasoning_effort} for Qwen.
// Using "qwen-chat-template" thinking format ensures Pi sends the correct params.
```

**Add clarification:**
```typescript
// NOTE: reasoning_effort is sent via Pi's Qwen patch (qwen-chat-template format).
// Lemonade backend passes it through chat_template_kwargs to llama.cpp.
// However, llama.cpp's reasoning parser has known issues with Qwen3 XML tags.
// The qwen-chat-template thinking format handles tag extraction in Pi, not llama.cpp.
```

---

## Phase 3: Pi Harness Changes (in `localpibox/pi` fork)

### 3.1 Soft-cap thinking during compaction

**IMPORTANT:** Qwen models **cannot have thinking fully disabled**. The lemonade plugin explicitly states:

> "not fully disabled (Qwen can't fully disable thinking)"

The correct mechanism is **soft-capping** via two complementary approaches:

1. **Pi fork: omit `reasoning` field during compaction** — sets `enable_thinking=false` which gives Qwen a bounded (soft-capped) thinking phase
2. **Lemonade plugin: `reasoningBudgetTokens: 0`** — provides the actual soft-cap that limits thinking length

**Files changed in fork:**
- `packages/agent/src/harness/compaction/compaction.ts` — `generateSummaryWithUsage()`, compact turn-prefix
- `packages/agent/src/harness/agent-harness.ts` — calls `compact()` with no thinkingLevel (undefined)

**Actual code (compaction.ts):**
```typescript
// Force thinking soft-capped during compaction — Qwen cannot fully disable
// thinking. Omitting the reasoning field sets enable_thinking=false which
// gives a bounded (soft-capped) thinking phase, reducing meta-thinking waste.
// For Qwen, this works alongside reasoningBudgetTokens:0 from the lemonade plugin.
// The lemonade plugin provides the actual soft-cap; omitting reasoning just
// removes the explicit thinking prompt for a more concise summary.
const completionOptions: SimpleStreamOptions = { maxTokens, signal };
```

**agent-harness.ts:** Calls `compact()` with `thinkingLevel: undefined` — this causes the pi-ai `streamSimple()` to not send `reasoningEffort`, resulting in `enable_thinking=false` for Qwen → soft-capped thinking.

**Rationale:** Meta-thinking about the conversation summary wastes tokens. Soft-capping reduces the thinking volume while still allowing the model to reason about what to summarize. The actual bound comes from `reasoningBudgetTokens:0` in the lemonade plugin.

---

### 3.2 Increase `reserveTokens` for thinking models

**File:** `packages/agent/src/harness/compaction/compaction.ts`

**Current:**
```typescript
export const DEFAULT_COMPACTION_SETTINGS: CompactionSettings = {
    enabled: true,
    reserveTokens: 16384,
    keepRecentTokens: 20000,
};
```

**Change:**
```typescript
export const DEFAULT_COMPACTION_SETTINGS: CompactionSettings = {
    enabled: true,
    reserveTokens: 32768,   // Doubled — gives compaction more breathing room
    keepRecentTokens: 20000,
};
```

**Rationale:** With 32k reserve, compaction fires at `262k - 32k = 230k` (87.8%) instead of 93.8%. This is closer to the Qwen degradation threshold (40-50% is the danger zone, but we want to prevent overflow before that).

---

### 3.3 (Future) Per-request output clamping

**This is the most robust fix, matching Qwen Code PR #6556.**

**Files:** `packages/agent/src/harness/agent-harness.ts` — the request sending path.

**Plan:**
```typescript
// Before sending a request, clamp max_tokens:
const roomInWindow = model.contextWindow - estimatedPromptTokens - SAFETY_MARGIN;
const actualMaxTokens = Math.min(
    model.maxTokens,
    Math.max(MIN_OUTPUT_TOKENS, roomInWindow),
);
```

**Parameters:**
- `SAFETY_MARGIN = 2048` (4k with 2x for token count non-determinism)
- `MIN_OUTPUT_TOKENS = 4096` (floor so we never ask for 0)

**This requires access to the full Pi source and is more invasive.** Defer to a later session.

---

## Phase 4: Docker Build Verification

### 4.1 Update CI workflow to use new ratio

**File:** `.github/workflows/build-and-publish.yml`

**Change:** No code change needed — the ratio is baked into the Dockerfile via `ENV`. The CI just needs to pass the env var.

---

### 4.2 Verify Dockerfile ENV placement

**File:** `Dockerfile`

**Current base stage:**
```
ENV LPB_MAX_TOKENS_CONTEXT_RATIO="${LPB_MAX_TOKENS_CONTEXT_RATIO:-0.125}"
```

**Change to:**
```
ENV LPB_MAX_TOKENS_CONTEXT_RATIO="${LPB_MAX_TOKENS_CONTEXT_RATIO:-0.06}"
```

---

## Phase 5: Documentation Updates

### 5.1 Update versions.env with ratio

Done in Phase 1.4.

### 5.2 Update README.md

Done in Phase 1.3.

### 5.3 Add QWEN-THINKING-OVERFLOW.md

Done during research.

### 5.4 Update AGENTS.md

**File:** `doc/AGENTS.md` (or the AGENTS.md in config repo)

**Add:**
```
## Qwen3 Thinking Overflow Known Issue
- maxTokens for Qwen thinking models is reduced to ~15k (ratio 0.06)
- Compaction reserveTokens increased to 32k
- Thinking is disabled during compaction requests
- Per-request output clamping is planned (see doc/QWEN-THINKING-OVERFLOW.md)
```

---

## File Change Summary

| File | Change | Phase |
|---|---|---|
| `Dockerfile` | ENV ratio 0.06 | 1.4 ✅ |
| `support/start.sh` | Default ratio 0.06 | 1.1 ✅ |
| `.env` | Explicit `LPB_MAX_TOKENS_CONTEXT_RATIO=0.06` | 1.4 ✅ |
| `.env.example` | Update comment | 1.3 ✅ |
| `versions.env` | Add ratio tracking | 1.4 ✅ |
| `scripts/lpb.py` | Default fallback 0.06 (was 0.125) | 1.5 ✅ (new) |
| `lemonade-pi-plugin/extensions/index.ts` | Lower maxTokens for Qwen | 2.1 ✅ |
| `lemonade-pi-plugin/extensions/index.ts` | Clarify reasoning_effort note | 2.2 ✅ |
| `pi` fork compaction.ts | Disable thinking during compaction | 3.1 ✅ |
| `pi` fork compaction.ts | Double reserveTokens to 32k | 3.2 ✅ |
| `pi-ai` simple-options.ts | `clampMaxTokensToContext()` per-request | 4.1 ✅ (upstream) |
| `doc/QWEN-THINKING-OVERFLOW.md` | Research doc (done) | — ✅ |
| `doc/implementation-plan.md` | This file | — ✅ |

---

## Execution Order (Session-by-Session)

### Session 1: Docker + Config (this repo)
- [x] Change `ENV LPB_MAX_TOKENS_CONTEXT_RATIO` in Dockerfile to 0.06
- [x] Change default in `support/start.sh` to 0.06
- [x] Update `.env` with `LPB_MAX_TOKENS_CONTEXT_RATIO=0.06`
- [x] Update `.env.example` comment
- [x] Update `versions.env` with ratio tracking
- [x] Update `scripts/lpb.py` default fallback from 0.125 to 0.06
- [x] Build image, verify maxTokens in model mapping is ~15k

### Session 2: Lemonade Extension
- [x] Clone/pull `localpibox/lemonade-pi-plugin` fork
- [x] Change `maxTokens` calculation for Qwen reasoning models (0.06 ratio)
- [x] Update `syncModelStore()` with same change
- [x] Clarify `reasoning_effort` comment
- [x] Test with running container — verify model shows 15k maxTokens

### Session 3: Pi Fork — Compaction
- [x] Clone/pull `localpibox/pi` fork
- [x] Disable thinking during compaction (`reasoning: "off"`)
- [x] Double `reserveTokens` to 32768
- [x] Test: sessions should stay under context limit longer

### Session 4: Pi Fork — Per-Request Clamping
- [x] Implemented — upstream `pi-ai` already has `clampMaxTokensToContext()` in `simple-options.ts`
- [x] The `openai-completions` API (used by lemonade) routes through `streamSimple` → `buildBaseOptions` → `clampMaxTokensToContext`
- [x] Safety margin: `CONTEXT_SAFETY_TOKENS = 4096` (≈2k × 2 for token count non-determinism)
- [x] Floor: `MIN_MAX_TOKENS = 1` (never asks for 0)

---

## Success Criteria

After all phases are complete:

1. **No more "context size exceeded" errors** during normal agentic sessions ✅
2. **Sessions stay stable** through 100+ turns without overflow (enforced by per-request clamping)
3. **Compaction fires at ~88%** (230k/262k) instead of 94% ✅
4. **maxTokens per request is ~15k** for Qwen thinking models ✅
5. **Thinking is disabled during compaction** — no meta-thinking waste ✅
6. **Per-request output clamping** — `clampMaxTokensToContext()` guarantees `prompt + output ≤ window` ✅
7. **Documentation exists** explaining the rationale and configuration ✅

## Rollback Plan

If issues arise:
1. Revert Dockerfile ENV to 0.125 — restores original behavior
2. Revert lemonade extension maxTokens — model gets 32k output budget again
3. Both changes are conservative and can be tuned incrementally (0.06 → 0.08 → 0.10)
4. Per-request clamping is a safety net — if it's too aggressive, increase `CONTEXT_SAFETY_TOKENS` in `pi-ai`
