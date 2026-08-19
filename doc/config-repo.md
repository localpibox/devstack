# Config Repo Reference

The **config repo** (`lpb-stack/config`, cloned to `/home/lpb/.pi/agent/`)
is the single source of truth for agent configuration, settings, skills,
and subagent definitions. It is installed into the devstack container at
boot by `start.sh`.

## Directory Structure

```
~/.pi/agent/
├── settings.json.template    → template (generated at boot → settings.json)
├── settings.json             → runtime config (NOT git-tracked, on host volume)
├── AGENTS.md                 → agent presets (model config, MCP servers, skills)
├── CONTRIBUTING.md           → contribution guidelines
├── VALIDATION.md             → validation rules for the stack
├── skills/
│   └── localpibox-repo-workflow/
│       ├── SKILL.md          → repository workflow skill
│       └── ...
├── agents/
│   ├── vision-analysis.md    → visual analysis subagent
│   ├── browser-automation.md → browser automation subagent
│   ├── exa-search.md         → web research subagent
│   ├── researcher.md         → researcher subagent
│   ├── README.md             → subagent registry
│   └── _template.md          → template for new subagents
├── mcp.json                  → MCP server configuration
├── .env                      → environment variables (promoted at boot)
├── .env.example              → template
└── git/github.com/lpb-stack/
    ├── lpb-memory/           → memory extension clone
    ├── pi-subagents/         → subagents extension clone
    └── lemonade-pi-plugin/   → lemonade provider extension clone
```

## settings.json Lifecycle

The settings file is **template-driven**, not git-tracked:

1. **Template**: `settings.json.template` ships in the config repo with
   `__LPB_VERSION__` placeholders
2. **Boot**: `start.sh` generates `settings.json` by replacing placeholders
3. **No model preconfigured**: user runs `/login lemonade` to set up the provider
4. **Persistence**: `settings.json` lives on the host volume — it survives
   container rebuilds
5. **Validation**: `lpb-config validate` checks settings.json pins match
   the current stack version

### Example pin format

```json
{
  "extensions": {
    "@lpb-stack/pi-subagents": {
      "git": "github.com/lpb-stack/pi-subagents@0.0.46-lpb-dev"
    },
    "@lpb-stack/lemonade-pi-plugin": {
      "git": "github.com/lpb-stack/lemonade-pi-plugin@0.0.46-lpb-dev"
    }
  }
}
```

Pins are synced by `lpb-config workspace sync --extensions`.

## Extension Clones

The `git/github.com/lpb-stack/` directory contains runtime clones of the
Pi extensions. They are **not baked into Docker images** — they update at
runtime via `pi update --extensions`.

| Directory | Repo | Role |
|---|---|---|
| `lpb-memory/` | `lpb-stack/lpb-memory` | Persistent memory extension |
| `pi-subagents/` | `lpb-stack/pi-subagents` | Subagent model registry |
| `lemonade-pi-plugin/` | `lpb-stack/lemonade-pi-plugin` | Lemonade provider plugin |

## Runtime State: lpb-memory Dir

The directory `~/.pi/agent/lpb-memory/` holds **runtime state** for the
memory extension — it is NOT in the config repo and NOT git-tracked:

| File | Purpose |
|---|---|
| `USER.md` | User preferences extracted from sessions (by NPU review) |
| `MEMORY.md` | Technical insights extracted from sessions |
| `failures.md` | Lessons learned from mistakes (failure detection) |

This data is created by the lpb-memory extension's subprocess review
system and persists across sessions. It is backed up with the host volume.

## Agents Directory

The `agents/` directory defines **subagent model configurations**. Each
`.md` file specifies:
- The `agent_type` and `model` to use
- The system prompt and tools available
- How the subagent should behave

For example, `vision-analysis.md` defines a subagent that uses the
local Qwen3.6 vision model to analyze browser screenshots.

## Skills Directory

The `skills/` directory contains **reusable procedures** (Pi skills).
Each skill is a directory with `SKILL.md` that defines:
- When to use it
- Step-by-step procedures
- Pitfalls and verification

The only skill shipped with the config repo is:
- `localpibox-repo-workflow` — manage the 6 LocalPibox repos (versioning,
  release, workspace sync)

## MCP Configuration

`mcp.json` configures MCP servers available to the agent. It references
servers like `exa`, `agent-browser`, and `context7-mcp` with their
respective connection details and API key sources.

## Quick Reference

```bash
# Check config repo state
lpb-config status

# Update config repo
lpb-config update

# Validate settings.json pins
lpb-config validate

# Sync extension pins to stack version
lpb-config workspace sync --extensions

# Reset config repo
lpb-config reset
```
