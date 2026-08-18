# lpb-memory Overview

The **lpb-memory** extension provides persistent, searchable memory for the
Pi coding agent. It runs background subprocess reviews to extract lessons,
preferences, and technical insights — making them available across sessions
via `memory_search`.

## What It Does

The extension performs four background operations using an NPU model
(such as `qwen3.5-9b-FLM`), independent of the main session model:

| Operation | When | What it does |
|---|---|---|
| **`review`** | Every 10 turns (configurable) | Scans recent conversation, extracts actionable memories |
| **`flush`** | Session end | Final review pass, saves extracted memories to store |
| **`correct`** | On user correction | Detects user corrections to AI behavior, records as lessons |
| **`consolidate`** | Periodic | Merges similar entries (reduces duplication) |

## Architecture

```
Main Session (Qwen3.6-35B)
  │
  ├─ AI calls memory_search → SQLite FTS5 search
  │
  └─ System prompt contains memory policy (tells AI to search)

Subprocess (NPU model, e.g. qwen3.5-9b-FLM)
  │
  ├─ review    → extracts memories every N turns
  ├─ flush     → final pass at session end
  ├─ correct   → captures user corrections
  └─ consolidate → merges similar entries
  │
  └─ Writes to: ~/.pi/agent/lpb-memory/{USER,MEMORY,failures}.md
```

### Memory Modes

| Mode | Behaviour |
|---|---|
| `policy-only` (default) | Injects memory **policy** into system prompt (40+ lines instructing AI to call `memory_search` when needed). Memory is NOT auto-injected. |
| `legacy-inject` | Injects full memory content (MEMORY.md, USER.md, failures.md) into system prompt every turn. AI sees memory automatically. |

**Policy-only** is more context-efficient but requires the AI to trust the
policy and call `memory_search` proactively. **legacy-inject** guarantees
visibility at the cost of ~2-3KB context per turn.

### Transport

| Transport | Behaviour |
|---|---|
| `subprocess` (default) | Runs review as a separate process using the NPU model. Offloaded from main session. |
| `direct` | Uses the main model directly (no NPU). Higher latency, no isolation. |

## Data Locations

Memory data lives on the **host volume** at `~/.pi/agent/lpb-memory/`:

| File | Content | Entries (typical) |
|---|---|---|
| `USER.md` | User preferences, workflows, constraints | 10-20 entries |
| `MEMORY.md` | Technical insights, tool discoveries | 5-15 entries |
| `failures.md` | Lessons from mistakes, corrections | 10-30 entries |

These files are written by the subprocess review and persisted across
container rebuilds.

## Configuration

Configuration lives in `lpb-memory-config.json` (generated from template
at boot, managed by `lpb-config memory setup`):

| Setting | Default | Description |
|---|---|---|
| `reviewTransport` | `subprocess` | Use NPU subprocess or direct |
| `llmModelOverride` | `qwen3.5-9b-FLM` | Model to use for reviews |
| `memoryMode` | `policy-only` | How memory is presented to AI |
| `memoryPolicyStyle` | `full` | Policy verbosity: `full` (40 lines) or `compact` (15 lines) |
| `nudgeInterval` | 10 | Extract memories every N turns |
| `autoConsolidate` | `true` | Merge similar entries automatically |
| `reviewTimeoutMs` | 300000 | Max time per review (5 min) |
| `consolidationTimeoutMs` | 300000 | Max time per consolidation (5 min) |

### Configuring

```bash
# Show current config
lpb-config memory show

# Interactive wizard
lpb-config memory setup

# Edit config directly
nano ~/.pi/agent/lpb-memory-config.json
```

## Backup & Privacy

- Memory files are plain text on the host volume — they survive container
  rebuilds but can be backed up manually:
  ```bash
  tar czf ~/lpb-memory-backup.tar.gz ~/.pi/agent/lpb-memory/
  ```
- Memory data is processed by the NPU model (runs locally). No data is
  sent to external services.
- To reset memory: delete the `lpb-memory/` directory contents and run
  `lpb-config memory setup` to reset the config.

## Quick Reference

```bash
# See what's in memory
cat ~/.pi/agent/lpb-memory/USER.md
cat ~/.pi/agent/lpb-memory/MEMORY.md
cat ~/.pi/agent/lpb-memory/failures.md

# Show current configuration
lpb-config memory show

# Configure interactively
lpb-config memory setup

# Backup
tar czf ~/lpb-memory-backup.tar.gz ~/.pi/agent/lpb-memory/

# Reset (careful: deletes all memory)
rm ~/.pi/agent/lpb-memory/*
lpb-config memory setup
```
