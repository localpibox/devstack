# Config Repo Validation Report

Validated: 2026-08-07

---

## Summary: ⚠️ README structure needs updating, content is correct

The actual config files (settings.json, mcp.json, skills, agents, support) are well-structured and functional. The **README.md structure section** has 4 discrepancies with the actual file layout.

---

## Findings

### 🔴 CRITICAL — README structure mismatches

| # | README claims | Actual | Impact |
|---|---|---|---|
| 1 | `support/bin/` directory | **Flat files** in `support/`: `browser`, `browser-state-cleanup.sh`, `session-uuid.ts`, `start.sh`, `validate-subagent-output.ts` | Directory structure misleading |
| 2 | `agents/researcher.md` (single file) | **5 files**: `README.md`, `_template.md`, `browser-automation.md`, `exa-search.md`, `researcher.md` | Missing 4 agent files from docs |
| 3 | `support/config/` + `support/docs/` shown | `support/config/` ✅ exists, `support/docs/` exists but not in README tree | Minor omission |
| 4 | `skills/` shown as dirs | Actually `skills/*/SKILL.md` (each skill dir has a SKILL.md file) | Minor — SKILL.md format is correct |

### 🟡 MEDIUM — Missing file in README

| # | File | Location | Status |
|---|---|---|---|
| 5 | `hermes-memory-config.json` | Repo root | **Not mentioned** in README. Contains: `{"consolidationTimeoutMs": 300000}` |

### 🟢 LOW — Content corrections

| # | Claim | Actual | Fix needed |
|---|---|---|---|
| 6 | `install.sh` output says "Thinking: high" | `settings.json` has `"defaultThinkingLevel": "medium"` | Update install.sh echo line |
| 7 | README says 6 packages | `settings.json` has 4 packages | README should reflect actual packages |

---

## Actual File Structure (correct)

```
config/
├── AGENTS.md                        # Global agent instructions
├── HERMES-MEMORY-CONFIG.JSON        # ⚠️ Missing from README
├── README.md
├── install.sh
├── .env.example
├── settings.json                    # ✅ Provider, model, thinking, packages
├── mcp.json                         # ✅ Exa, agent-browser, chrome-devtools
├── skills/
│   ├── agent-browser-mcp-integration/SKILL.md
│   ├── browser-validation/SKILL.md
│   └── mcp-vision-analysis/SKILL.md
├── agents/
│   ├── README.md                    # ⚠️ Missing from README
│   ├── _template.md                 # ⚠️ Missing from README
│   ├── browser-automation.md        # ⚠️ Missing from README
│   ├── exa-search.md                # ⚠️ Missing from README
│   └── researcher.md
└── support/
    ├── browser                      # Source script for browser env
    ├── browser-state-cleanup.sh     # ⚠️ Flat, not in bin/
    ├── browser-validate.ts          # Structured validation utility
    ├── session-uuid.ts              # CLI session ID generator
    ├── start.sh                     # Container entrypoint
    ├── validate-subagent-output.ts  # Parent-side JSON validation
    ├── config/
    │   ├── agent-browser-action-policy.json
    │   └── subagent-browser-prompt.txt
    ├── docs/
    │   └── subagent-spawning-pattern.md
    └── schemas/
        ├── browser-validation-schema.json
        └── subagent-browser-schema.json
```

---

## settings.json — Packages list

**README claims:** 6 packages (pi fork, lemonade-pi-plugin, lpb-memory, pi-mcp-adapter, pi-subagents, pi-powerline-footer)

**Actual (4 packages):**
1. `git:github.com/localpibox/lemonade-pi-plugin@patches/api-key-auth`
2. `npm:pi-mcp-adapter`
3. `npm:@tintinweb/pi-subagents`
4. `npm:pi-powerline-footer`

**Note:** `pi` (monorepo) and `lpb-memory` are NOT in settings.json — they're installed at runtime via devstack's config seeding. Only the extensions live in settings.json.

---

## mcp.json — Accurate ✅

All 3 servers match the README claims:
- `exa` — Web search (requires EXA_API_KEY)
- `agent-browser` — Browser automation (tools: core,network,tabs,state,react,debug)
- `chrome-devtools` — Diagnostics (enabled: false)

---

## Skills — Content validated ✅

All 3 SKILL.md files:
1. **agent-browser-mcp-integration** — Browser automation with MCP
2. **browser-validation** — Full validation pipeline (navigate, snapshot, screenshot, vitals, a11y, vision)
3. **mcp-vision-analysis** — Visual analysis using local Qwen3.6-35B vision model

All reference `/opt/pi-support` for support files (correct — install.sh copies support/ there).

---

## Agents — Content validated ✅

5 agent files:
1. **README.md** — How agents work, usage examples
2. **_template.md** — Copy template for custom agents
3. **browser-automation.md** — Browser testing agent (mcp tools, sonnet model)
4. **exa-search.md** — Web research agent (mcp tools, sonnet model)
5. **researcher.md** — Lightweight web research (uses Qwen3.6 model, direct MCP tools)

---

## Support Files — Content validated ✅

| File | Purpose | Status |
|---|---|---|
| `browser` | Source script for browser env vars | ✅ |
| `browser-state-cleanup.sh` | Housekeeping for browser sessions | ✅ |
| `browser-validate.ts` | Structured validation with Zod + vision | ✅ |
| `session-uuid.ts` | CLI session ID generator | ✅ |
| `start.sh` | Container entrypoint | ✅ |
| `validate-subagent-output.ts` | Parent-side JSON validation | ✅ |
| `config/agent-browser-action-policy.json` | Destructive action gates | ✅ |
| `config/subagent-browser-prompt.txt` | Subagent browser prompt template | ✅ |
| `docs/subagent-spawning-pattern.md` | Orchestration docs | ✅ |
| `schemas/browser-validation-schema.json` | Validation report schema | ✅ |
| `schemas/subagent-browser-schema.json` | Subagent result schema | ✅ |

---

## install.sh — Minor issue

Line at end of script says:
```
echo "  Thinking: high"
```

Should be:
```
echo "  Thinking: medium"
```

Since `settings.json` has `"defaultThinkingLevel": "medium"`.

---

## hermes-memory-config.json

```json
{
  "consolidationTimeoutMs": 300000
}
```

This file controls the lpb-memory extension's consolidation timeout. It should be documented in the README or removed if not needed at the repo level (since it's already mentioned in AGENTS.md).

---

## Conclusion

The config repo is **well-structured and functional**. The main work needed is:
1. Fix README structure to match actual file layout
2. Add missing files to README (hermes-memory-config.json, agents README)
3. Fix install.sh echo line
4. Clarify packages list (4 extensions, not 6)
