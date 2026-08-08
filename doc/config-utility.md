# Config Utility — `lpb config` / `pi-config`

Design for a configuration management utility for **MCP servers** and **Pi
extensions**, operated from the host via `lpb --config` (or directly inside the
container).

## Scope & operating model

- The utility **manages the config repo** (git-cloned to `~/.pi/` by start.sh).
  Key files: `mcp.json`, `settings.json`, `AGENTS.md`, `lpb-memory-config.json`, `agents/`, `skills/`.
  
- `localpibox/config` is **git-cloned at startup** to `~/.pi/` — Pi reads directly from the repo root. The utility **never commits back to it**. Drift
  from the preset is expected (runtime is the authoritative, user-specific
  copy).
- The utility lives **inside the container** (baked at
  `/opt/pi-support/bin/pi-config`) because devstack itself is normally
  **not mounted** in the workspace. The host-side `lpb --config` subcommand
  only drives it over `podman/docker exec`, exactly like `lpb --shell` execs
  `bash`.

```
Host                          Container
┌──────────────┐   exec ───▶  ┌──────────────────────────────┐
│ lpb --config │  <command>   │  /opt/pi-support/bin/pi-config│
│ (lpb.py)     │              │  └── reads/writes ~/.pi/agent/*│
└──────────────┘              │  └── edits settings.json#packages│
                              │  └── triggers pi package install│
                              │  └── /reload for next session  │
                              └──────────────────────────────┘
```

## Entrypoints

### 1. Host: `lpb --config [args]` (new subcommand in scripts/lpb.py)

Mirrors `lpb --shell`:

```
lpb --config                       # interactive TUI inside container
lpb --config servers list          # non-interactive, prints JSON/table
lpb --config servers add exa ...
lpb --config servers disable chrome-devtools
lpb --config extensions add npm:pi-foo
lpb --config reload                # signal /reload for next pi session
lpb --config --reset               # re-seed ~/.pi/agent/ from preset
```

Implementation: reuse `ContainerClient.containers_exec`:

```python
elif cfg.config_mode:                       # --config flag
    ensure_container()                      # start if not running
    args = ["pi-config", *EXTRA_ARGS]
    ret = c.containers_exec(cfg.container_name, args, tty=True, interactive=True)
```

### 2. In-container: `pi-config` (Python CLI at `/opt/pi-support/bin/pi-config`)

A single Python file (like `lpb.py` / `sync-workspace.py`, stdlib-only), with a
small command tree and both TUI (readline/dialog) and non-interactive modes.

## Command tree (v1)

```
pi-config
  servers
    list                 # name, status (enabled/disabled/connected), tools
    add <name> --command ... --arg ... [--env K=V] [--disabled]
    remove <name>
    enable <name>        # sets "disabled": false / removes field
    disable <name>       # sets "disabled": true
    set <name> <json>    # replace a server def (validation)
  extensions
    list                 # pi list (installed packages from settings#packages)
    add <spec>           # pi install <git:|npm: ref>  (installs + writes packages)
    remove <spec>        # pi remove <spec>
    update               # pi update --extensions
  settings
    get <key>   | set <key> <json>      # model, theme, thinking, mcp.*
  reload                 # write configs, notify next pi session to /reload
  audit                  # diff/validate a single file or all; --json
  reset [--from-preset]  # re-seed ~/.pi/agent from preset location
  --help
```

## Write rules (single source of truth for the runtime)

- **MCP servers** → edit `mcp.json#mcpServers`, use `"disabled": true` to
  disable (never `"enabled": false` — pi-mcp-adapter only honors `disabled`).
  The MCP panel TUI (`/mcp`) *shows* disabled servers but cannot re-enable
  them (`mcp-panel.ts` returns early on `connectionStatus === "disabled"`);
  only `/mcp enable <name>` works. `pi-config servers enable` fills this gap.
- **Extensions** → delegate to `pi install <spec>` / `pi remove <spec>` /
  `pi update --extensions` (they handle node_modules install **and** write
  `settings.json#packages`).
- **Other settings** → edit the matching `~/.pi/agent/*.json`.
- Always validate with `jq`/JSON parse before writing; back up the file first
  (`*.bak`); never touch runtime-only state (`mcp-cache.json`, `sessions/`,
  `trust.json`, `auth.json`, `lpb-memory/`).
- `reload`/`audit` report drift, disabled servers, and installed packages.

## Confirmed decisions

1. **Extension install = delegate to pi's native package manager.**
   `pi install <source>`, `pi remove <source>`, `pi update --extensions`, and
   `pi list` already handle BOTH the node_modules install AND writing
   `settings.json#packages`. The utility therefore shells out to these rather
   than reimplementing install. Editing `settings.json#packages` alone does
   NOT trigger an install (confirmed) — you must run `pi install`.

   ```
   pi-config extensions add    npm:@x/y   →  pi install npm:@x/y
   pi-config extensions remove npm:@x/y   →  pi remove  npm:@x/y
   pi-config extensions update            →  pi update --extensions
   pi-config extensions list              →  pi list
   ```
2. **`--reset` does a fresh fetch of the preset.** If the preset isn't already
   baked into the image, `--reset` does `git fetch`/`pull` of
   `localpibox/config` (which also picks up updates if the runtime has drifted
   from git), then copies the preset files into `~/.pi/agent/`, preserving
   runtime-exclusive state (`mcp-cache.json`, `sessions/`, `trust.json`,
   `auth.json`, `lpb-memory/`). One-way re-seed; never a write-back branch.
3. **Trigger vs. restart.** MCP `mcp.json` + extension `settings.json#packages`
   are read by the adapter / pi at **startup**. A freshly installed extension
   is picked up at the **next pi launch**; a running session can pick up config
   via `/reload` (best-effort — extension packages are most reliably loaded on
   a new launch). `pi-config` therefore prints: `changes apply at next pi
   start; run /reload in a running session for config`. Where possible,
   `lpb --config` ends by launching a fresh `pi` session.
4. **Simple interactive yes/no CLI for v1.** Bare `lpb --config` runs a
   small menu (readline): numbered commands + yes/no confirmations before
   writes and package installs. A full TUI is deferred.

## Fork & repoint analysis

Forking `localpibox/devstack`, personalizing it, and repointing to a
user-managed fork set works at three layers (`lpb.stack.env` is the documented
single source for fork pointers):

| Layer | Where URL/ref is set | Repoint effort | Path |
|---|---|---|---|
| **Extensions** (lemonade-pi-plugin, lpb-memory, pi-subagents, mcp-adapter) | runtime config `settings.json#packages` | 🟢 trivial, no rebuild | edit `packages` / `pi install git:<fork>/<repo>`; applied at next startup via `pi update --extensions` |
| **Config preset** (localpibox/config) | `lpb.stack.env` `LPB_CONFIG_FORK`/`LPB_CONFIG_REF` → Dockerfile `ARG CONFIG_FORK`/`CONFIG_REF` | 🟡 rebuild, or runtime | rebuild `--build-arg CONFIG_FORK=...`, **or** runtime `git -C ~/.local/pi-config remote set-url origin <fork>` (no rebuild); `pi-config reset` re-seeds from it |
| **Pi core** | `lpb.stack.env` `LPB_PI_FORK`/`LPB_PI_REF` → Dockerfile `ARG` | 🔴 image rebuild | fork `localpibox/pi`, set engine + `LPB_IMAGE_CLI`, rebuild |
| **Dev workspace checkout** (pi + 5 repos into `workspace/`) | `tools/workspace.manifest.json` | 🟢 easy | edit manifest URLs/refs for `sync-workspace.py` |

Gaps addressed by this change:
- The config-preset clone in the Dockerfile was **hardcoded** to
  `localpibox/config.git`; it now reads `LPB_CONFIG_FORK`/`LPB_CONFIG_REF`
  (via `ARG CONFIG_FORK`/`ARG CONFIG_REF`), so a fork can repoint it from
  `lpb.stack.env` like the pi core.
- Repo URLs still appear in both `lpb.stack.env` (pi) and
  `tools/workspace.manifest.json` (all 5) — these serve different purposes
  (image build vs dev workspace) and are intentionally separate for now.

## Bootstrap integration

- `start.sh` (or the image build) places `pi-config` at
  `/opt/pi-support/bin/`.
- First-run already copies preset → `~/.pi/agent/`; `pi-config audit` runs
  there to confirm a clean seed.
- `--reset` provides the on-demand re-seed path for later.

## Non-goals (v1)

- No git write-back to `localpibox/config` (preset is seed-only).
- No editing of the devstack source tree (not mounted).
- No auth/secret management beyond env placeholders for MCP servers.
