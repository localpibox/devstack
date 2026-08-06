# Branch Analysis Summary

**Generated:** 2026-08-03
**Target branch:** `lpb` (stable)
**Current version:** `v0.1.0-lpb`

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✓ | Merged into `lpb` (safe to delete) |
| ⚠ | Superseded by another branch |
| ❌ | Abandoned / incompatible |
| 🔴 | Must merge before next release (critical) |
| 🟡 | Should merge before release (high) |
| 🟠 | Nice to have (medium priority) |
| 🟢 | Low priority, merge anyway |

---

## 1. pi (`localpibox/pi`)

| Branch | Status | Priority | Action |
|--------|--------|----------|--------|
| **`lpb`** | `50e24690` | STABLE | Current release base |
| `main` | — | — | Fork main (not used by CI) |
| `fix-budget-tokens-fetch` | **PENDING** | 🔴 HIGH | Qwen infinite reasoning loop fix |
| `patches/qwen-reasoning-effort` | ✓ MERGED | — | Delete (identical to lpb) |
| `patches/overflow-case4` | ✓ MERGED | — | Delete (identical to lpb) |
| `upstream/main` | — | — | 174 commits ahead (mostly docs changes) |

### Pending: `fix-budget-tokens-fetch`
**Commits:** 2 (`3183ce87` + `2a477783`)
**What it does:**
- Adds `reasoning_budget_tokens` to OpenAI completions API
- Prevents Qwen models from entering infinite reasoning loops
- Reads from `compat.reasoningBudgetTokens` instead of `model.reasoningBudgetTokens`
**Why critical:** Qwen models will hang/burn tokens without this fix.

---

## 2. devstack (`localpibox/devstack`)

| Branch | Status | Priority | Action |
|--------|--------|----------|--------|
| **`lpb`** | `a3cb493` | STABLE | Current release (includes versioning docs) |
| `main` | — | — | Legacy (same as lpb) |
| `fix/qwen-thinking-overflow-2026` | ✓ MERGED | — | Delete (merged into lpb) |
| `refactor/cli-web-split` | ✓ MERGED | — | Delete (merged into lpb) |
| `fix/opt-pi-support-permission` | ❌ ABANDONED | — | Delete remote (incompatible redesign) |

### Abandoned: `fix/opt-pi-support-permission`
- 31 files, 573 additions, 3,980 deletions
- Full architecture redesign replacing `lpb.py` with `localpistack.sh` + `docker-compose.yml`
- Incompatible with current lpb architecture → DO NOT MERGE

---

## 3. lemonade-pi-plugin (`localpibox/lemonade-pi-plugin`)

| Branch | Status | Priority | Action |
|--------|--------|----------|--------|
| **`lpb`** | `93cfa73` | STABLE | Current release |
| `main` | — | — | Legacy (same as lpb) |
| `patches/api-key-auth` | **PENDING** | 🔴 CRITICAL | MUST merge |
| `patches/qwen-vision` | **PENDING** | 🟢 LOW | Merge (trivial) |
| `upstream/main` | — | — | Reference only |

### CRITICAL: `patches/api-key-auth`
**Commits:** 14 (`7297995` + 13 parents → `fc97dbe`)
**What it does:**
1. Fixes Lemonade provider auth type (was `oauth`, now `api_key`) — without this, provider silently fails to register
2. Adds Qwen-chat-template thinking format support
3. Fixes `/v1` URL path in base config
4. Adds Qwen-MTP model detection via labels/recipe
5. Adds `reasoningBudgetTokens` support (from `fc97dbe`)
6. Makes `MAX_TOKENS_CONTEXT_RATIO` configurable via env var
7. Syncs `models-store.json` in subprocesses
**Why critical:** Without this, the Lemonade provider won't work at all.

### LOW: `patches/qwen-vision`
**Commits:** 1 (`1da9e36`)
**What it does:** Updates repo URLs from `lemonade-sdk` to `localpibox`
**Why low:** Documentation only.

---

## 4. pi-hermes-memory (`localpibox/pi-hermes-memory`)

| Branch | Status | Priority | Action |
|--------|--------|----------|--------|
| **`lpb`** | `661ad52` | STABLE | Current release (memory extension disabled in settings.json) |
| `main` | — | — | Legacy (same as lpb) |
| `fix/subprocess-provider` | ⚠ SUPERSEDED | — | Delete (use batch-consolidation instead) |
| `fix/batch-consolidation` | **PENDING** | 🟡 HIGH | MUST merge (supersedes subprocess-provider) |
| `upstream/main` | — | — | Reference only |

### HIGH: `fix/batch-consolidation` (supersedes `fix/subprocess-provider`)
**Commits:** 12 (`0e17f4e` + parent chain → `dc2477b`)
**What it does:**
1. Isolates memory operations from session context (prevents context overflow)
2. Passes current model to consolidation subprocess (all paths)
3. Auto-detects and loads provider plugins in subprocesses
4. Fixes file path handling (`join()` vs `path.join()`)
5. Reactivates model override across ALL LLM subprocess paths
6. Adds deterministic pre-filtering to batch consolidation process
**Why high:** Critical for memory extension stability; prevents context overflow and model propagation bugs.

---

## 5. config (`localpibox/config`)

| Branch | Status | Priority | Action |
|--------|--------|----------|--------|
| **`lpb`** | `db1ba82` | STABLE | Current release (includes VERSION + versioning docs) |
| `main` | — | — | Legacy (same as lpb) |
| `fix/exa-mcp-tool-names` | **PENDING** | 🟠 MEDIUM | Merge |
| `lpb` | — | — | (already created and pushed) |

### MEDIUM: `fix/exa-mcp-tool-names`
**Commits:** 1 (`e106cc2`)
**What it does:** Fixes Exa MCP agent preset tool names:
- `search` → `web_search_exa`
- `getContents` → `web_fetch_exa`
**Impact:** Exa-search agent preset currently broken.

---

## Merge Priority Summary

| Priority | Branch | Repo | Impact if Not Merged |
|----------|--------|------|---------------------|
| 🔴 CRITICAL | `patches/api-key-auth` | lemonade-pi-plugin | Lemonade provider fails to register |
| 🔴 HIGH | `fix-budget-tokens-fetch` | pi | Qwen models enter infinite reasoning loops |
| 🟡 HIGH | `fix/batch-consolidation` | pi-hermes-memory | Memory extension fails with context overflow |
| 🟠 MEDIUM | `fix/exa-mcp-tool-names` | config | Exa-search agent preset broken |
| 🟢 LOW | `patches/qwen-vision` | lemonade-pi-plugin | Repo URL mismatch (cosmetic) |

---

## Branches to Delete (Safe Cleanup)

| Repo | Branch | Reason |
|------|--------|--------|
| `pi` | `patches/qwen-reasoning-effort` | Merged into lpb |
| `pi` | `patches/overflow-case4` | Merged into lpb |
| `devstack` | `fix/qwen-thinking-overflow-2026` | Merged into lpb |
| `devstack` | `refactor/cli-web-split` | Merged into lpb |
| `devstack` | `fix/opt-pi-support-permission` | Abandoned redesign |
| `pi-hermes-memory` | `fix/subprocess-provider` | Superseded by batch-consolidation |

---

## Next Steps

To ship the next release (`v0.2.0-lpb`):

1. **Merge in priority order:**
   - `lemonade-pi-plugin` → `origin/patches/api-key-auth`
   - `pi` → `fix-budget-tokens-fetch`
   - `pi-hermes-memory` → `origin/fix/batch-consolidation`
   - `config` → `origin/fix/exa-mcp-tool-names`
   - `lemonade-pi-plugin` → `origin/patches/qwen-vision`

2. **Bump version:** Update `VERSION` files to `v0.2.0-lpb` on all repos

3. **Tag and push:** Push `lpb` branches → CI triggers → tags `:v0.2.0-lpb-cli` and `:v0.2.0-lpb-web`

4. **Enable memory extension** (if desired): Add `pi-hermes-memory` back to `settings.json` packages

5. **Clean up branches:** Delete merged/superseded branches from remotes
