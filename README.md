# LocalPibox DevStack

Containerized development environment for the LocalPibox Pi stack: Docker setup with Lemonade, VSCodium, and full agent toolchain.

## What it runs

- **VSCodium** — VS Code-compatible editor (port 3000)
- **Lemonade** — Local LLM server for Qwen3.6 (port 13305)
- **Pi.dev** — AI coding agent with local model support
- **Agent-Browser** — Browser automation for testing and analysis

## Quick Start

```bash
# From the project directory
devstack .

# Or from parent directory
devstack /path/to/project
```

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `EXA_API_KEY` | Exa MCP server API key |
| `CONNECTION_TOKEN` | OpenVSCode auth token |
| `EDITOR_HOST` | Editor host (default: 0.0.0.0) |
| `ED_PORT` | Editor port (default: 3000) |

## Repository Structure

This repo contains the Docker configuration. The Pi agent configuration is in:
- **[config](https://github.com/localpibox/config)** — settings, skills, agents, support files

## LocalPibox Stack

1. **pi** — Forked monorepo with reasoning_effort patch
2. **lemonade-pi-plugin** — Qwen model detection
3. **config** — Pi settings, skills, agents
4. **devstack** — This repo (Docker environment)
