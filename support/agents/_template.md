---
# ──────────────────────────────────────────────────────────────
# Agent Preset Template
#
# Copy this file to .pi/agents/<your-agent>.md and customize.
# The pi-subagents extension loads all .md files in this directory.
#
# ──────────────────────────────────────────────────────────────

name: my-agent
description: One-line description of what this agent does
tools: read, bash, grep, find, ls          # Built-in tools (comma-sep or * for all)
extensions: true                           # Load all extension tools
exclude_extensions: vscode                 # Optional: block specific extensions
model: sonnet                              # Model override (fuzzy match: "sonnet" → provider/claude-sonnet-4-*)
thinking: medium                           # off | low | medium | high | xhigh | max
max_turns: 25                              # Wrap-up warning before hard abort
prompt_mode: replace                       # replace (system prompt) or append
inherit_context: false                     # Fork parent conversation into agent
run_in_background: true                    # Default execution mode
isolated: false                            # No extension tools
isolation: worktree                        # Git worktree isolation
memory: project                            # Persistent memory scope: user | project | local | omit
enabled: true                              # Hide if false

# ──────────────────────────────────────────────────────────────
# System Prompt
#
# This markdown body becomes the agent's system prompt.
# Write clear instructions, output schemas, and constraints here.
#
# Tips:
#   1. Start with a role statement
#   2. Define the output format (JSON schema if structured)
#   3. Set hard constraints (e.g., "NO preamble, NO code fences")
#   4. Describe how to use available tools
# ──────────────────────────────────────────────────────────────

# Role: [Agent Name]
#
# You are a [description of agent role].
#
# ## Output Schema
# Return ONLY valid JSON matching this schema. No preamble. No markdown.
# {
#   "status": "PASS" | "FAIL" | "WARN",
#   "summary": "<brief result>",
#   "details": [ ... ]
# }
#
# ## Instructions
# 1. [First step]
# 2. [Second step]
# ...
#
# ## Constraints
# - [Hard rule 1]
# - [Hard rule 2]
