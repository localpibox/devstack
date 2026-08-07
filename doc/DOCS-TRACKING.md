# Documentation Tracking

Pending items, things to refine, and review-needed topics.
Created: 2026-08-07 · Last updated: 2026-08-07

---

## Completed Validations ✅

### 1. Pi Fork Validation (2026-08-07)
- **Doc:** [PI-FORK-VALIDATION.md](PI-FORK-VALIDATION.md)
- **Status:** ✅ Fully wired and functional
- **Findings:** All 6 patches properly wired, no missing links
- **Changes made:** Fixed README `reasoning_budget_tokens` file paths
- **Commit:** `0c76eb3`

### 2. Lemonade Plugin Validation (2026-08-07)
- **Doc:** [LEMONADE-PLUGIN-VALIDATION.md](LEMONADE-PLUGIN-VALIDATION.md)
- **Status:** ✅ Correctly wired to llama.cpp via qwen-chat-template format
- **Findings:** Plugin bridges Pi's reasoning_effort API to Lemonade/llama.cpp chat_template_kwargs
- **Changes made:**
  - `DEFAULT_MAX_TOKENS_CONTEXT_RATIO`: 0.06 → 0.125 (Qwen uses QWEN_RATIO 0.06)
  - Consolidated duplicate `isQwenReasoningModel` in syncModelStore → uses global function
- **Commit:** `1e374d5`


### 3. Config Repo Validation (2026-08-07)
- **Doc:** [CONFIG-REPO-VALIDATION.md](CONFIG-REPO-VALIDATION.md)
- **Status:** ✅ README structure needs updating, content is correct
- **Findings:** settings/mcp.json/skills/agents/support all accurate
- **Changes needed:**
  - README structure: support/bin→flat, agents missing 4 files, missing hermes-memory-config.json
  - install.sh echo: "high" → "medium"
  - README packages list: 6 claims → 4 actual
- **Commit:** `9146128`

---

## Removed References (to be redone when stabilized)

### 3. Dev workspace manifest
- **Where removed:** devstack/README.md "What each component maps to" table
- **Reference:** `tools/workspace.manifest.json` + `sync-workspace.py`
- **Reason:** Files don't exist yet, will be redone when stable
- **Owner:** TBD
- **Status:** ⬜ To be redone

### 4. Config sync skill
- **Where removed:** GitHub Pages site (localpibox.github.io/index.html)
- **Reference:** `config-repo-sync/SKILL.md` — "reconcile the preset repo with the runtime copy"
- **Reason:** Skill doesn't exist yet, needs to be redone when stabilized
- **Owner:** TBD
- **Status:** ⬜ To be redone

---

## Structure Validation Needed

### 5. `support/` → `support/bin/` reorganization
- **Current state:** Support files are flat in `support/`
- **Question:** Should these be organized under `support/bin/` with subdirectories?
- **Affected docs:** devstack/README.md Directory Structure, config/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

### 6. Config `agents/` directory structure
- **Current README says:** `agents/researcher.md` (single file)
- **Actual structure:** README.md, _template.md, browser-automation.md, exa-search.md, researcher.md
- **Question:** Are all agent files working as expected?
- **Affected docs:** config/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

---

## Feature/Code Validation Needed

### 7. `scripts/publish.sh` in lemonade-pi-plugin
- **Current README says:** "Drop NPM publishing" but publish.sh still exists
- **Question:** Is publishing intended? Keep or drop?
- **Affected docs:** lemonade-pi-plugin/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

### 8. devstack `QUICK-START.md` vs README Quick Start section
- **Current state:** Both exist — which is authoritative?
- **Question:** Should they be unified or kept separate?
- **Affected docs:** devstack/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

### 9. config repo — full content validation
- **What to check:** settings.json, mcp.json, skills/, agents/, support/, install.sh
- **Question:** Does the README structure match actual files? Do skills/agents work?
- **Affected docs:** config/README.md
- **Owner:** TBD
- **Status:** ⬜ **Next item to validate**

### 10. lpb-memory — code validation
- **What to check:** src/index.ts — subprocess reviews, SQLite search, background learning
- **Question:** Does the code actually implement what the README claims?
- **Affected docs:** lpb-memory/README.md
- **Owner:** TBD
- **Status:** ⬜ To be validated

### 11. devstack/Dockerfile + lpb.py — runtime validation
- **What to check:** Docker build pipeline, lpb commands (--web, --ssh, --shell, --logs)
- **Question:** Do the container and launcher work as described?
- **Affected docs:** devstack/README.md
- **Owner:** TBD
- **Status:** ⬜ To be validated

---

## Content Review (low priority, review when convenient)

### 12. devstack Directory Structure — items to add later
- **Missing from docs:** `.pi/prompts/` (6 files), `.pi/skills/` (6 files), `GH-PROFILE-DRAFT.md`
- **Decision:** Include or leave as implicit?
- **Status:** ⬜ Needs review

### 13. lpb-memory README — origin note accuracy
- **Current:** Says "originated from chandra447/pi-hermes-memory" with comparison table
- **Question:** Is the origin note still accurate? Fully severed?
- **Affected docs:** lpb-memory/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs review

### 14. GitHub Pages site
- **What to check:** All links live, content accurate, badges correct
- **Status:** ⬜ Needs review

### 15. devstack/doc/*.md — content accuracy
- **Files:** ARCHITECTURE.md, BRANCH-ANALYSIS.md, BRANCH-STRATEGY.md, QWEN-THINKING-OVERFLOW.md, STACK-UPKEEP.md, config-utility.md, implementation-plan.md
- **Question:** Do these docs match the actual codebase?
- **Status:** ⬜ Needs review

### 16. config/AGENTS.md — agent instructions
- **Question:** Do the agent instructions match runtime behavior?
- **Status:** ⬜ Needs review

---

## Meta

### How to use this file
- Items are listed in order of urgency: completed → removed references → structure → features → low priority
- When an item is resolved:
  1. Update the "Status" to ✅ Done
  2. Add a note with date and what was decided/changed
  3. Reference the commit(s) that addressed it
- For items needing decision: add "Decision:" and "Rationale:" when resolved

### Validation Progress
- **Completed:** 3/16 (pi fork, lemonade plugin)
- **Next:** lpb-memory code validation (item 9)
- **Pending:** 14 items
