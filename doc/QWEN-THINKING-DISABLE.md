# Qwen3 Thinking "Disable" — Reality Check

> Created: 2026-08-07  
> Status: **Documentation correction only** — code is correct, docs are wrong

## TL;DR

The Pi fork source code already handles Qwen thinking correctly:
- `reasoningBudgetTokens: 0` soft-caps thinking (prevents runaway)
- Compaction omits `reasoning` field → Qwen gets `enable_thinking: false` → **soft-capped** thinking (not off)
- The lemonade plugin already implements this correctly
- **The code is fine.** The issue is only in documentation that says "thinking is disabled" when it should say "thinking is soft-capped"

---

## 1. The Problem

The Qwen3.6-35B-A3B-MTP-GGUF model **cannot have thinking fully disabled**.

This is explicitly acknowledged in the lemonade-pi-plugin code (`extensions/index.ts`):

```typescript
// Reasoning budget tokens for Qwen-MTP models.
// reasoning_budget_tokens=0 gives a bounded (soft-capped) thinking phase —
// not fully disabled (Qwen can't fully disable thinking), but prevents
// runaway thinking blocks that exhaust the max_tokens budget.
// Values: 0=soft-capped, positive=token count budget, -1=unbounded.
const QWEN_REASONING_BUDGET_TOKENS = 0;
```

Despite this, the implementation plan (`doc/implementation-plan.md`) and the Pi fork's compaction code comments claim that thinking can be "disabled" during compaction. **The claim is wrong — Qwen can't be fully disabled.**

## 2. What Actually Happens

### The Qwen Thinking Protocol

| `reasoningEffort` value | `params.enable_thinking` | Qwen behavior |
|---|---|---|
| `undefined` / `"off"` | `false` | **Soft-capped** thinking (still produces thinking, just bounded) |
| `"low"` | `true` | Thinking with low effort |
| `"medium"` | `true` | Thinking with medium effort |
| `"high"` | `true` | Thinking with high effort |

### The `reasoningBudgetTokens` Mechanism

| `reasoningBudgetTokens` | Effect |
|---|---|
| `0` | Soft-capped thinking (bounded but not disabled) |
| `>0` | Hard token budget |
| `-1` | Unbounded thinking |

## 3. Current Code State

The Pi fork source (branch `lpb`, latest commit `3769f54a6`) has the correct implementation:

| Fix | Mechanism | Status |
|---|---|---|
| `maxTokens` ratio 0.06 | lemonade plugin + `lpb.conf.env` | ✅ Applied |
| `reasoningBudgetTokens: 0` | lemonade plugin compat object | ✅ Applied |
| `reserveTokens: 32768` | pi-agent-core compaction defaults | ✅ Applied |
| Compaction omits `reasoning` | pi-agent-core compaction | ✅ Applied (comment says "off", should say "soft-capped") |
| `clampMaxTokensToContext()` | pi-ai per-request clamping | ✅ Applied |

**Plus one unreleased fix on the fork**:
- `07bab7948 fix(ai): fix reasoningBudgetTokens type and property access` — fixes the type/access for `reasoningBudgetTokens`

## 4. What Needs Changing

### Documentation (LOW effort, HIGH impact)

1. **Pi fork comments**: Change "Force thinking off" → "Force thinking soft-capped" in:
   - `packages/agent/src/harness/compaction/compaction.ts` (2 locations)

2. **`doc/implementation-plan.md`**: Replace Phase 3.1 description with correct `reasoningBudgetTokens: 0` mechanism

3. **`doc/QWEN-THINKING-OVERFLOW.md`**: Add `reasoningBudgetTokens` to the mitigations list

4. **`doc/QWEN-THINKING-DISABLE.md`**: This file (corrects the "disable" misconception)

### Code (already correct, needs rebuild to include latest fix)

The fork has an unreleased `reasoningBudgetTokens` type fix (`07bab7948`). This needs to be rebuilt and redeployed to pick it up.

## 5. Rebuild Checklist

1. **Verify** fork source compiles: `cd workspace/pi && npm install && npm run build`
2. **Run tests**: `cd workspace/pi && npm test` (or `test.sh`)
3. **Package tgz**: `npm publish` or `npm pack` from the fork
4. **Rebuild Docker image**: `podman build -t localpibox/devstack:cli -f Dockerfile .`
5. **Restart container**: `lpb --stop && lpb`
6. **Verify** reasoning budget works: run a session and check that thinking blocks are bounded
