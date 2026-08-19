# Environment Variables Reference

Environment variables are managed across two layers: **runtime defaults**
(baked into the image), **container `.env`** (user overrides), and **shell
environment** (highest priority).

## Priority Chain (highest → lowest)

1. Shell environment (`export LPB_...`)
2. Devstack `.env` file (at container root, maps `LPB_*` → bare name)
3. Runtime defaults (`lpb.conf.env` baked into image)
4. Hardcoded fallback

## LPB_ Variables

These are the variables read by the `lpb` launcher and `lpb-config`:

| Variable | Default | Purpose |
|---|---|---|
| `LPB_VERSION` | last-used version file | Stack version to run |
| `LPB_TAG` | `dev` | Pipeline selector: `dev` or `main` |
| `LPB_CONTAINER_NAME` | `lpb-stack` | Podman container name |
| `LPB_MODE` | `web` | Image flavour: `cli` or `web` |
| `LPB_RUNTIME` | `podman` | Container runtime: `podman` or `docker` |
| `LPB_MAX_TOKENS_CONTEXT_RATIO` | `0.06` | Max tokens ratio for Qwen reasoning models |

## Bridged Variables (LPB_ → bare name)

`start.sh` at container boot promotes `LPB_*` variables to bare names that
third-party tools expect. This is the **LPB_ bridge**:

| LPB_ Prefix | Bare Name | Used By |
|---|---|---|
| `LPB_EXA_API_KEY` | `EXA_API_KEY` | Exa MCP server |
| `LPB_CONTEXT7_API_KEY` | `CONTEXT7_API_KEY` | Context7 MCP server |
| `LPB_CONNECTION_TOKEN` | `CONNECTION_TOKEN` | OpenVSCode |
| `LPB_EDITOR_HOST` | `HOST` | OpenVSCode |
| `LPB_ED_PORT` | `ED_PORT` | OpenVSCode |

This means setting `LPB_EXA_API_KEY` in the container `.env` file is sufficient —
`start.sh` automatically promotes it to `EXA_API_KEY` the MCP server needs.

## Per-Pipeline Overrides

`lpb.stack.env`, `lpb.stack.dev.env`, and `lpb.stack.main.env` define
pipeline-specific values:

| Variable | dev | main |
|---|---|---|
| `LPB_PI_REF` | `lpb-dev` | `lpb` |
| `LPB_CONFIG_REF` | `dev` | `main` |

The `lpb --tag dev` or `lpb --tag main` flag selects which pipeline profile
to use.

## In-Image Environment

Variables inside the running container (read by Pi and extensions):

| Variable | Purpose |
|---|---|
| `PI_WORKSPACE_ROOT` | Workspace root path |
| `AGENT_DIR` | Config repo directory |
| `LPB_AGENT_GIT` | Extension git clones directory |
| `LEMONADE_BASE_URL` | Model API endpoint (`http://127.0.0.1:13305/v1`) |
| `VISION_MODEL` | Vision model ID (`Qwen3.6-35B-A3B-MTP-GGUF`) |
| `AGENT_BROWSER_SESSION` | Browser session isolation ID |
| `AGENT_BROWSER_ALLOWED_DOMAINS` | Navigation allowlist |
| `AGENT_BROWSER_MAX_OUTPUT` | Max chars for snapshot output (4000) |

## Configuration File Reference

| File | Purpose |
|---|---|
| `.env.example` | Template for container environment variables |
| `.env` | Actual environment (auto-generated on first run) |
| `lpb.conf.env` | Global defaults for the lpb launcher |
| `lpb.stack.env` | Stack-wide variables (shared by dev and main) |
| `lpb.stack.dev.env` | Dev-pipeline overrides |
| `lpb.stack.main.env` | Main-pipeline overrides |

## Quick Reference

```bash
# Override pipeline
export LPB_TAG=main
lpb /project

# Use docker instead of podman
export LPB_RUNTIME=docker
lpb /project

# Check what version is selected
echo $LPB_VERSION

# Pin a specific version
export LPB_VERSION=0.0.54-lpb-dev
lpb /project
```
