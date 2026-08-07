# Documentation Tracking

Pending items, things to refine, and review-needed topics.
Created: 2026-08-07

---

## Removed References (to be redone when stabilized)

### 1. Dev workspace manifest
- **Where removed:** devstack/README.md "What each component maps to" table
- **Reference:** `tools/workspace.manifest.json` + `sync-workspace.py`
- **Reason:** Files don't exist yet, will be redone when stable
- **Owner:** TBD
- **Status:** ⬜ To be redone

### 2. Config sync skill
- **Where removed:** GitHub Pages site (localpibox.github.io/index.html)
- **Reference:** `config-repo-sync/SKILL.md` — "reconcile the preset repo with the runtime copy"
- **Reason:** Skill doesn't exist yet, needs to be redone when stabilized
- **Owner:** TBD
- **Status:** ⬜ To be redone

---

## Structure Validation Needed

### 3. `support/` → `support/bin/` reorganization
- **Current state:** Support files are flat in `support/`:
  - `support/browser`
  - `support/browser-state-cleanup.sh`
  - `support/browser-validate.ts`
  - `support/session-uuid.ts`
  - `support/start.sh`
  - `support/validate-subagent-output.ts`
- **Question:** Should these be organized under `support/bin/` with subdirectories?
- **Affected docs:** devstack/README.md Directory Structure, config/README.md (structure section)
- **Owner:** TBD
- **Status:** ⬜ Needs validation

### 4. Config `agents/` directory structure
- **Current README says:** `agents/researcher.md` (single file)
- **Actual structure:**
  - `agents/README.md`
  - `agents/_template.md`
  - `agents/browser-automation.md`
  - `agents/exa-search.md`
  - `agents/researcher.md`
- **Question:** Are all agent files working as expected? Should the README reflect the full structure?
- **Affected docs:** config/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

---

## Feature/Code Validation Needed

### 5. `scripts/publish.sh` in lemonade-pi-plugin
- **Current README says:** "publish.sh — NPM publishing" but then says "Drop NPM publishing"
- **Reality:** `scripts/publish.sh` **still exists** and contains full npm publish logic
- **Question:** Is publishing intended? Should we keep or drop it?
- **Affected docs:** lemonade-pi-plugin/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

### 6. devstack `QUICK-START.md` vs README Quick Start section
- **Current state:** Both exist:
  - `devstack/QUICK-START.md` (standalone file, 2562 bytes)
  - `devstack/README.md` has a "Quick Start" section (duplicates content)
- **Question:** Which is authoritative? Should they be unified or kept separate?
- **Affected docs:** devstack/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs validation

---

## Content Review (low priority, review when convenient)

### 7. devstack Directory Structure — items to add later
These exist but are not in the README's Directory Structure:
- `.pi/prompts/` — 6 OpenSpec prompt files (opsx-apply.md, opsx-archive.md, etc.)
- `.pi/skills/` — 6 OpenSpec skills (openspec-apply-change, etc.)
- `GH-PROFILE-DRAFT.md` — GitHub profile draft (temporary?)
- `.pi/mcp.json` — MCP config in devstack root

**Decision:** Should these be included in the Directory Structure, or left as implicit?

### 8. lpb-memory README — origin note accuracy
- **Current:** Says "originated from chandra447/pi-hermes-memory" with comparison table
- **Question:** Is the origin note still accurate? Has the fork relationship been fully severed?
- **Affected docs:** lpb-memory/README.md
- **Owner:** TBD
- **Status:** ⬜ Needs review

---

## Meta

### How to use this file
- Items are listed in order of urgency: removed references → structure → features → low priority
- When an item is resolved:
  1. Update the "Status" to ✅ Done
  2. Add a note with date and what was decided/changed
  3. Reference the commit(s) that addressed it
- For items needing decision: add "Decision:" and "Rationale:" when resolved

### Last reviewed
2026-08-07
