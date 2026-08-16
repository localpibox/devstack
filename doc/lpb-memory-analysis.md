# lpb-memory Extension Analysis Report

**Date:** 2026-08-16
**Extension:** pi-hermes-memory v0.9.1 (fork)
**Status:** Memory writes OK, memory reads into main session rarely happen

---

## Current Architecture

### Memory Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      Main Session                               │
│                                                                 │
│  User messages ─────────────────────────────────────────┐       │
│                                                         │       │
│  System prompt:     ◄── policy-only mode ──┐            │       │
│  (NO memory injected)                      │            │       │
│                                            │            │       │
│  memory_search tool ◄── AI must proactively│            │       │
│                  │                        search        │       │
│                  ▼                        to find       │       │
│  SQLite FTS5 DB ◄──────────────────────────────────────┘       │
│  (lpb-memory/sessions.db)                                      │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │ subprocess (NPU model)
         │
┌────────┴──────────────────────────────────────────────────────┐
│  Background Operations (offloaded to NPU)                     │
│                                                               │
│  review   ──► every 10 turns, extracts memories              │
│  flush    ──► session end, saves memories                    │
│  correct  ──► detects user corrections                       │
│  consolidate ──► merges similar entries                     │
└───────────────────────────────────────────────────────────────┘
```

### Current Configuration

| Setting | Value | Status |
|---|---|---|
| `memoryMode` | `policy-only` | **CORE ISSUE** — no auto-injection |
| `memoryPolicyStyle` | `full` | 40-line policy prompt in system |
| `reviewTransport` | `subprocess` | ✅ Offloads to NPU |
| `llmModelOverride` | `qwen3.5-9b-FLM` | ⚠️ Known routing issues |
| `nudgeInterval` | 10 turns | Review every 10 turns |
| `autoConsolidate` | true | Entries merged periodically |

### Memory Store Content

| File | Entries | Quality |
|---|---|---|
| `MEMORY.md` | 5 | Good — technical insights |
| `USER.md` | 16 | Good — preferences, workflows |
| `failures.md` | 18 | Good — corrections, failures |

---

## Root Cause Analysis

### Problem: Memory written but not read back

**Primary cause: `policy-only` mode**

In `policy-only` mode (the default), lpb-memory does NOT inject memory into the system prompt. Instead it injects a 40-line `<memory-policy>` block that tells the AI to use `memory_search` when needed.

The AI must:
1. Recognize it needs historical context
2. Proactively call `memory_search`
3. Use the results

**This is a trust problem** — the AI needs to know it should search, and the model needs to comply.

### Secondary issues

1. **Policy prompt is long** (40+ lines) — takes context space, may be skimmed
2. **NPU model routing unreliable** — subprocess sometimes uses main model instead
3. **No proactive injection** — unlike "legacy-inject" mode, memory never appears automatically
4. **AI doesn't know what's in memory** — without seeing it, can't know if search is useful

---

## Suggestions

### A. Quick Wins (no code changes)

#### 1. Switch to `legacy-inject` mode

Change `memoryMode` from `policy-only` to `legacy-inject` in `lpb-memory-config.json`:

```json
{
  "reviewTransport": "subprocess",
  "llmModelOverride": "qwen3.5-9b-FLM",
  "reviewTimeoutMs": 300000,
  "consolidationTimeoutMs": 300000,
  "memoryMode": "legacy-inject"
}
```

**Effect:** Memory (MEMORY.md, USER.md, failures.md) is injected into system prompt every turn. AI sees it without searching.

**Trade-off:** Uses more context tokens (~2-3KB of memory), but guarantees visibility.

#### 2. Compact the policy prompt

Switch `memoryPolicyStyle` to `"compact"` (15 lines instead of 40):

```json
{
  "memoryPolicyStyle": "compact"
}
```

**Effect:** Less context waste, more room for actual memory.

#### 3. Increase review frequency

Lower `nudgeInterval` to capture memories sooner:

```json
{
  "nudgeInterval": 5
}
```

**Effect:** Memory extracted every 5 turns instead of 10. Faster feedback loop.

#### 4. Fix NPU model routing

The failures.md has 12 entries about NPU model not routing correctly. This is a known issue. Debug path exists in `pi-child-process.ts` — check if `llmModelOverride` survives to CLI args.

### B. Medium Effort (extension config changes)

#### 5. Hybrid mode: inject high-value targets only

If `legacy-inject` uses too much context, add a config option to inject only specific targets:

```json
{
  "memoryMode": "legacy-inject",
  "injectedTargets": ["user", "failure"]
}
```

Inject USER.md and failures.md (high-value), skip MEMORY.md (lower priority).

**Requires:** Small code change in `prompt-context.ts` to support target filtering.

#### 6. Add project-scoped memory injection

Currently `buildPromptContext` checks for project store. Ensure devstack project memory is separate and injected:

```json
{
  "projectsMemoryDir": "~/.pi/agent/projects-memory/devstack"
}
```

### C. Long Term (extension code changes)

#### 7. Smart injection: inject relevant memory on demand

Instead of all-or-nothing, inject memory entries matching current conversation topics. The FTS5 index already supports this:

```typescript
// Pseudocode
const recentTopics = extractTopics(last5Messages);
const relevantMemory = await store.searchMemories(recentTopics, { limit: 5 });
return relevantMemory.map(m => m.content).join("\n");
```

**Requires:** Topic extraction logic + integration into `buildPromptContext`.

#### 8. Memory summary in system prompt

Instead of full entries, inject a bullet-point summary:

```
<memory-summary>
• User prefers subprocess transport for memory ops
• User wants root-cause fixes, not band-aids
• NPU model routing issue known (12 failure entries)
• LocalPibox stack: 6 repos, single-source versioning
• Pi extension requires /new to reload changes
</memory-summary>
```

**Requires:** Summarization pass (can use NPU model).

#### 9. Failure injection on relevant triggers

Inject failures from `failures.md` when the AI makes similar mistakes. Pattern-match failure keywords against AI output:

```
AI says: "let's merge these branches"
→ Inject: "NEVER delete or modify branches without explicit confirmation"
```

**Requires:** Failure keyword indexing + trigger detection.

---

## Recommended Action Plan

### Phase 1: Immediate (today)
1. [ ] Switch to `legacy-inject` mode in `lpb-memory-config.json`
2. [ ] Set `memoryPolicyStyle` to `"compact"`
3. [ ] Lower `nudgeInterval` to 5

### Phase 2: Debug (this week)
4. [ ] Fix NPU model routing — check `execChildPrompt` CLI args
5. [ ] Verify subprocess uses `qwen3.5-9b-FLM` (monitor NPU activity)

### Phase 3: Optimize (future)
6. [ ] Implement hybrid injection (high-value targets only)
7. [ ] Add memory summarization to reduce context usage
8. [ ] Smart injection based on conversation topics

---

## Memory Content Quality Assessment

**Current memory is HIGH QUALITY** — entries are specific, actionable, and well-categorized. The extraction is working well. The problem is purely on the READ side (memory not appearing in main session).

### MEMORY.md (5 entries) — Technical insights
- Meta-entry feedback loop prevention
- Subprocess model testing differences
- Extension code caching behavior
- NPU timeout vs model-not-found distinction
- JIT compilation caching

### USER.md (16 entries) — Preferences
- NPU model for background ops ✅
- Subprocess transport ✅
- Root-cause fixes over band-aids (4 entries — repetitive, could consolidate)
- No hardcoded values ✅
- Lean workflows ✅
- Branch protection instruction ✅
- Versioning orchestration (2 similar entries — could consolidate)

### failures.md (18 entries) — Lessons
- 12 NPU routing failures (repetitive — same root cause)
- 4 corrections
- 2 insights about consolidation filtering

**Consolidation opportunity:** Many entries are duplicates of the same lesson. `autoConsolidate` is enabled but hasn't merged them — may need prompt tuning or lower threshold.
