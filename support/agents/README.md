# Agent Presets

Custom agent configurations for the pi-subagents extension. Each `.md` file
defines a specialized agent with its own tools, system prompt, model, and
thinking level.

## How It Works

The pi-subagents extension loads `.pi/agents/*.md` files as custom agent types.
Each file uses YAML frontmatter to configure the agent, and the markdown body
becomes the system prompt.

Usage from any Pi session:
```
Agent({
  subagent_type: "agent-name",
  prompt: "Describe the task clearly...",
  description: "Brief description",
  run_in_background: true,
})
```

## Presets

| Agent | Purpose | Thinking | Tools |
|---|---|---|---|
| `exa-search` | Web research via Exa MCP | high | mcp proxy |
| `browser-automation` | Browser testing via agent-browser MCP | high | mcp proxy |

## File Format

```yaml
---
name: agent-name
description: What this agent does
tools: read, bash, grep, find, ls  # built-in tools (comma-sep or * for all)
extensions: true                   # load all extension tools
exclude_extensions: vscode         # optional: block specific extensions
model: sonnet                      # model override (fuzzy match)
thinking: high                     # off | low | medium | high | xhigh | max
max_turns: 30                      # wrap-up warning before hard abort
prompt_mode: replace               # replace (vs append) system prompt
inherit_context: false             # fork parent conversation
run_in_background: false           # default execution mode
isolated: false                    # no extension tools
isolation: worktree                # git worktree isolation
memory: project                    # persistent memory scope
enabled: true                      # hide if false
---
# System prompt body — markdown
# This becomes the agent's system prompt.
# Write clear instructions, output schemas, and constraints here.
```

## Tool Selection

- **Built-in tools**: `read`, `bash`, `grep`, `find`, `ls`, `edit`, `write`, `mcp`
- **Wildcard**: `tools: *` grants all built-in tools (default for general-purpose)
- **Extension tools**: `extensions: true` loads all extension tools
- **Extension denylist**: `exclude_extensions: vscode` blocks specific extensions
- **Tool denylist**: `disallowed_tools: edit,write` blocks specific built-in tools

## System Prompt Tips

1. **Start with a role statement**: `# Role: Web Research Specialist`
2. **Define output format**: Include a JSON schema if structured output is needed
3. **Set constraints**: `You MUST return only valid JSON — no preamble, no code fences.`
4. **Describe tools**: `Use the mcp proxy tool to search Exa: mcp({ tool: "search", args: { query: "..." } })`

## Creating a New Agent

1. Create `.pi/agents/<name>.md`
2. Add YAML frontmatter with configuration
3. Write the system prompt in the markdown body
4. Test with `Agent({ subagent_type: "<name>", prompt: "..." })`

The new agent type will be available immediately — no restart needed.
