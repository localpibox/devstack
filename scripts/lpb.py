#!/usr/bin/env python3
"""lpb - LocalPibox Devstack launcher

Usage:
    lpb [/path/to/project]              Start VSCodium at project (or home if no path)
    lpb -i, --interactive               Start in interactive mode (get shell inside container)
    lpb --stop                          Stop the container
    lpb --remove                        Stop + remove container + state dirs
    lpb --logs                          Stream container logs
    lpb --update                        Pull latest image
    lpb --config                        Show config file location
    lpb --help                          Show usage

VSCodium options (before project path):
    --host <HOST>          Host to listen on (default: from .env or localhost)
    --port <PORT>          Port to listen on (default: from .env or 8000)
    --token <TOKEN>        Connection token (default: from .env or devsession)
    --without-token        Disable auth (trusted networks only!)
    --data-dir <PATH>      Server data directory
    --user-data-dir <PATH> User data directory (multiple instances)
    --ext-dir <PATH>       Extensions root path
    --base-path <PATH>     Web UI subpath (e.g. /ide)

Config priority (highest wins):
    1. CLI flags
    2. Project .env (LPB_* vars)
    3. Project override (~/.localpibox/devstack/projects/<name>)
    4. Global config (~/.localpibox/devstack/config)
    5. Built-in defaults
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from typing import Optional

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".localpibox", "devstack")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config")
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
LAST_PROJECT_FILE = os.path.join(CONFIG_DIR, "last-project")


class Config:
    image_name = "ghcr.io/localpibox/devstack:latest"
    container_name = "localpibox"
    container_cmd = ""
    port = 8000
    host = "localhost"
    token = "devsession"
    without_token = False
    state_dir = os.path.join(HOME, ".localpibox", "state")
    browser_dir = os.path.join(HOME, ".localpibox", "agent-browser")
    project_dir = ""
    project_name = ""
    open_home = False
    interactive = False
    command = "run"


cfg = Config()
_ERR, _WRN, _RSV = "\033[31m", "\033[33m", "\033[0m"


def err(msg, hint=""):
    print(f"{_ERR}Error: {msg}{_RSV}", file=sys.stderr)
    if hint:
        print(f"  {_WRN}{hint}{_RSV}", file=sys.stderr)

def info(msg):
    print(msg)

def run_cmd(args, timeout=120):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", 1
    except FileNotFoundError:
        return "", f"not found: {args[0]}", 127

def ensure_container_cmd():
    if cfg.container_cmd:
        return
    cfg.container_cmd = shutil.which("podman") or shutil.which("docker") or ""
    if not cfg.container_cmd:
        err("podman or docker is required",
            "Install one of them and retry. See https://podman.io or https://docs.docker.com")
        sys.exit(1)

def is_podman():
    return "podman" in cfg.container_cmd

# ─── Container lifecycle ─────────────────────────────────────────────────────

def _list_names(flags=None):
    ensure_container_cmd()
    cmd = [cfg.container_cmd, "ps"]
    if flags:
        cmd.extend(flags)
    cmd += ["--format", "{{.Names}}"]
    out, _, rc = run_cmd(cmd)
    return [n.strip() for n in out.strip().splitlines() if n.strip()] if rc == 0 else []

def container_running():
    return cfg.container_name in _list_names()

def container_exists():
    return cfg.container_name in _list_names(["-a"])

def stop_container():
    ensure_container_cmd()
    run_cmd([cfg.container_cmd, "stop", "-t", "30", cfg.container_name])

def remove_container():
    ensure_container_cmd()
    run_cmd([cfg.container_cmd, "rm", "-f", cfg.container_name])

def ensure_stopped():
    if container_running():
        stop_container()
    if container_exists():
        remove_container()
        return True
    return False

def pull_image():
    ensure_container_cmd()
    _, _, rc = run_cmd([cfg.container_cmd, "image", "inspect", cfg.image_name])
    if rc != 0:
        info(f"Pulling {cfg.image_name}...")
        _, eo, rc = run_cmd([cfg.container_cmd, "pull", cfg.image_name])
        if rc != 0:
            short = eo.strip().splitlines()[-1] if eo.strip() else "unknown"
            err("Failed to pull image", short[:200])
            sys.exit(1)

# ─── Path / mount ────────────────────────────────────────────────────────────

def resolve_path(p):
    return os.path.abspath(os.path.expanduser(p).replace("${HOME}", HOME))

def detect_mount_flags(project_dir):
    ensure_container_cmd()
    _, stderr, _ = run_cmd([
        cfg.container_cmd, "run", "--rm", "--name", "_lpb_mnt_test",
        "-v", f"{project_dir}:/tmp/mnt:Z",
        "alpine:latest", "sh", "-c", "echo ok",
    ])
    run_cmd([cfg.container_cmd, "rm", "-f", "_lpb_mnt_test"])
    if stderr and re.search(r"selinux|relabeling|permission", stderr, re.IGNORECASE):
        return ":z"
    return ":Z"

# ─── Config loading ──────────────────────────────────────────────────────────

_ENV_MAP = {
    "LPB_IMAGE_NAME": "image_name", "LPB_CONTAINER_NAME": "container_name",
    "LPB_PORT": "port", "LPB_EDITOR_HOST": "host", "LPB_CONNECTION_TOKEN": "token",
    "LPB_STATE_DIR": "state_dir", "LPB_BROWSER_DIR": "browser_dir",
}

def load_config_file():
    if not os.path.isfile(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'(?:export\s+)?(\w+)=(.*)', line)
                if m:
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass

def _apply_env():
    for ek, attr in _ENV_MAP.items():
        val = os.environ.get(ek)
        if val:
            setattr(cfg, attr, int(val) if attr == "port" else val)

def load_project_env(project_dir):
    env_file = os.path.join(project_dir, ".env")
    if not os.path.isfile(env_file):
        return
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key.startswith("LPB_"):
                    os.environ[key] = value
                    os.environ[key[4:]] = value
    except OSError:
        pass

def load_project_override(name):
    p = os.path.join(PROJECTS_DIR, name)
    if not os.path.isfile(p):
        return
    try:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'(?:export\s+)?(\w+)=(.*)', line)
                if m:
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass

def apply_overrides(project_dir=None, project_name=None):
    load_config_file()
    _apply_env()
    if project_dir and os.path.isfile(os.path.join(project_dir, ".env")):
        load_project_env(project_dir)
        _apply_env()
    if project_name:
        load_project_override(project_name)
        for ek, attr in [("LPB_PROJECT_PORT", "port"), ("LPB_PROJECT_TOKEN", "token"), ("LPB_PROJECT_HOST", "host")]:
            val = os.environ.get(ek)
            if val:
                setattr(cfg, attr, int(val) if attr == "port" else val)

# ─── CLI parsing ─────────────────────────────────────────────────────────────

def parse_cli(args):
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--host":
            if i+1 >= len(args): err("--host requires a value"); sys.exit(1)
            cfg.host = args[i+1]; i += 2
        elif a == "--port":
            if i+1 >= len(args): err("--port requires a value"); sys.exit(1)
            try: cfg.port = int(args[i+1])
            except ValueError: err(f"--port requires an integer, got: {args[i+1]}"); sys.exit(1)
            i += 2
        elif a == "--token":
            if i+1 >= len(args): err("--token requires a value"); sys.exit(1)
            cfg.token = args[i+1]; i += 2
        elif a == "--without-token":
            cfg.without_token = True; i += 1
        elif a in ("--data-dir",):
            if i+1 >= len(args): err("--data-dir requires a value"); sys.exit(1)
            cfg.data_dir = args[i+1]; i += 2
        elif a in ("--user-data-dir",):
            if i+1 >= len(args): err("--user-data-dir requires a value"); sys.exit(1)
            cfg.user_data_dir = args[i+1]; i += 2
        elif a in ("--ext-dir",):
            if i+1 >= len(args): err("--ext-dir requires a value"); sys.exit(1)
            cfg.ext_dir = args[i+1]; i += 2
        elif a in ("--base-path",):
            if i+1 >= len(args): err("--base-path requires a value"); sys.exit(1)
            cfg.base_path = args[i+1]; i += 2
        elif a in ("-i", "--interactive"):
            cfg.interactive = True; i += 1
        elif a in ("--stop", "-s"):
            cfg.command = "stop"; i += 1
        elif a in ("--remove", "-r"):
            cfg.command = "remove"; i += 1
        elif a in ("--logs", "-l"):
            cfg.command = "logs"; i += 1
        elif a in ("--update", "-u"):
            cfg.command = "update"; i += 1
        elif a in ("--config", "-c"):
            cfg.command = "config"; i += 1
        elif a in ("--help", "-h", "help"):
            cfg.command = "help"; i += 1
        elif a == "--":
            positional.extend(args[i+1:]); break
        elif a.startswith("--"):
            err(f"Unknown option: {a}", "Run 'lpb --help' for usage."); sys.exit(1)
        else:
            positional.append(a); i += 1
    if positional:
        cfg.project_dir = positional[0]


# ─── Help ────────────────────────────────────────────────────────────────────

HELP = (
    "lpb \u2014 LocalPibox Devstack launcher\n\n"
    "Usage:\n"
    "  lpb [/path/to/project]           Start VSCodium at project (or home if no path)\n"
    "  lpb -i, --interactive            Start in interactive mode (shell inside container)\n"
    "  lpb --stop                       Stop the container\n"
    "  lpb --remove                     Stop + remove container + state dirs\n"
    "  lpb --logs                       Stream container logs\n"
    "  lpb --update                     Pull latest image\n"
    "  lpb --config                     Show config file location\n"
    "  lpb --help                       Show this help\n\n"
    "VSCodium options (before project path):\n"
    "  --host <HOST>          Host to listen on (default: from .env or localhost)\n"
    "  --port <PORT>          Port to listen on (default: from .env or 8000)\n"
    "  --token <TOKEN>        Connection token (default: from .env or devsession)\n"
    "  --without-token        Disable auth (trusted networks only!)\n"
    "  --data-dir <PATH>      Server data directory\n"
    "  --user-data-dir <PATH> User data directory (multiple instances)\n"
    "  --ext-dir <PATH>       Extensions root path\n"
    "  --base-path <PATH>     Web UI subpath (e.g. /ide)\n\n"
    "Config files:\n"
    "  Global:  ~/.localpibox/devstack/config\n"
    "  Project: ~/.localpibox/devstack/projects/<project-name>\n\n"
    "Examples:\n"
    "  lpb                                         Open VSCodium at ~ (user picks project)\n"
    "  lpb /home/user/myproject                    Open VSCodium at project\n"
    "  lpb /home/user/myproject --port 8080        Custom port\n"
    "  lpb --host 0.0.0.0 --token mysecret         LAN access with custom token\n"
    "  lpb --without-token                         No auth (localhost only!)\n"
    "  lpb -i                                      Interactive shell inside container"
)

def cmd_help():
    print(HELP); sys.exit(0)

def cmd_stop():
    ensure_container_cmd()
    if not container_running():
        info(f"Container '{cfg.container_name}' is not running.")
        sys.exit(0)
    info(f"Stopping {cfg.container_name}...")
    _, _, rc = run_cmd([cfg.container_cmd, "stop", "-t", "30", cfg.container_name])
    if rc != 0: err("Failed to stop", "Check: lpb --logs"); sys.exit(1)
    remove_container()
    info("Stopped and removed.")

def cmd_remove():
    ensure_container_cmd()
    remove_container()
    for d in (cfg.state_dir, cfg.browser_dir):
        if os.path.isdir(resolve_path(d)):
            shutil.rmtree(resolve_path(d), ignore_errors=True)
    info("Removed devstack (container, state dir, browser dir).")

def cmd_logs():
    ensure_container_cmd()
    if not container_exists():
        err("Container not found", "Run 'lpb --remove' then 'lpb' to start fresh.")
        sys.exit(0)
    _, _, rc = run_cmd([cfg.container_cmd, "logs", "-f", cfg.container_name])
    if rc != 0: err("Failed to follow logs"); sys.exit(1)

def cmd_update():
    ensure_container_cmd()
    info(f"Pulling {cfg.image_name}...")
    _, _, rc = run_cmd([cfg.container_cmd, "pull", cfg.image_name])
    if rc != 0: err("Failed to pull image"); sys.exit(1)

def cmd_config():
    info(f"Config file: {CONFIG_FILE}")
    info(f"Projects:    {PROJECTS_DIR}")
    info(f"State dir:   {resolve_path(cfg.state_dir)}")
    info(f"Browser dir: {resolve_path(cfg.browser_dir)}")


# ─── cmd_run ─────────────────────────────────────────────────────────────────

def _build_url():
    """Build the connection URL from the RESOLVED cfg.host and cfg.port.

    These values come from:
      1. CLI --host / --port flags
      2. Project .env (LPB_EDITOR_HOST / LPB_ED_PORT)
      3. Global config
      4. Defaults

    The server inside the container will be listening on exactly these values,
    so the URL must match.
    """
    if cfg.without_token:
        return f"http://{cfg.host}:{cfg.port}/"
    return f"http://{cfg.host}:{cfg.port}/?tkn={cfg.token}"


def cmd_run():
    ensure_container_cmd()

    # ── 1. Resolve project directory ─────────────────────────────────────
    project_dir = cfg.project_dir
    if not project_dir:
        if os.path.isfile(LAST_PROJECT_FILE):
            with open(LAST_PROJECT_FILE) as f:
                project_dir = f.read().strip()
    if not project_dir:
        cfg.open_home = True
        project_dir = HOME

    project_dir = resolve_path(project_dir)
    if not os.path.isdir(project_dir):
        err(f"directory not found: {project_dir}")
        sys.exit(1)

    # ── 2. Project name & validation ─────────────────────────────────────
    cfg.project_name = os.path.basename(project_dir)
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$', cfg.project_name):
        err(f"project name '{cfg.project_name}' contains invalid characters for volume mounts",
            "Use only alphanumeric characters, dots, hyphens, and underscores.")
        sys.exit(1)

    # ── 3. Mount path inside container ───────────────────────────────────
    # When open_home (no project specified), mount at /home/dev/workspace
    # so the user gets the welcome screen. Otherwise mount at
    # /home/dev/workspace/<NAME>.
    if cfg.open_home:
        mount_path = "/home/dev/workspace"
    else:
        mount_path = f"/home/dev/workspace/{cfg.project_name}"

    # ── 4. Show summary ──────────────────────────────────────────────────
    # At this point cfg.port, cfg.host, cfg.token are already resolved from
    # .env / overrides / CLI, so we show the ACTUAL values the container
    # will use.
    info(f"Devstack: {cfg.project_name}")
    info(f"  Image:    {cfg.image_name}")
    info(f"  Project:  {project_dir} \u2192 {mount_path}")
    info(f"  Editor:   http://{cfg.host}:{cfg.port}")
    if cfg.without_token:
        info("  Auth:     none (\u26a0 unsecured)")
    else:
        info(f"  Token:    {cfg.token[:8]}...")
    info("")
    if cfg.open_home:
        info("Starting VSCodium \u2014 select a project in the welcome screen.")
    else:
        info(f"Starting VSCodium \u2014 opening {cfg.project_name}.")
    info("")

    # ── 5. Resolve & ensure state dirs ───────────────────────────────────
    resolved_state = resolve_path(cfg.state_dir)
    dir_browser = resolve_path(cfg.browser_dir)
    os.makedirs(resolved_state, exist_ok=True)
    os.makedirs(dir_browser, exist_ok=True)

    # ── 6. Stop existing container ───────────────────────────────────────
    if container_running():
        info("Stopping existing devstack container...")
        stop_container()

    # ── 7. Pull image ────────────────────────────────────────────────────
    pull_image()

    # ── 8. Detect SELinux mount flags ────────────────────────────────────
    mount_flags = detect_mount_flags(project_dir)

    # ── 9. Remove stale stopped containers ───────────────────────────────
    if container_exists():
        info(f"Removing stale container '{cfg.container_name}'...")
        remove_container()

    # ── 10. Build & run container ────────────────────────────────────────
    info("Running...")

    run_args = [cfg.container_cmd, "run", "-d",
                "--name", cfg.container_name,
                "--network", "host"]

    if is_podman():
        run_args += ["--userns", "keep-id"]

    if cfg.interactive:
        run_args += ["-it"]

    run_args += [
        "-e", f"LPB_ED_PORT={cfg.port}",
        "-e", f"LPB_EDITOR_HOST={cfg.host}",
        "-e", f"LPB_DEVCONTAINER_WORKSPACE_DIR={mount_path}",
        "-e", f"LPB_CONNECTION_TOKEN={cfg.token}",
        "-e", "LPB_STATE_DIR=/home/dev/.pi",
        "-v", f"{project_dir}:{mount_path}{mount_flags}",
        "-v", f"{resolved_state}:/home/dev/.pi{mount_flags}",
        "-v", f"{dir_browser}:/home/dev/.agent-browser{mount_flags}",
    ]

    run_args.append(cfg.image_name)

    stdout, stderr, rc = run_cmd(run_args)
    container_id = stdout.strip()

    if rc != 0 or not container_id:
        err("failed to start container")
        if stderr:
            print(stderr, file=sys.stderr)
        print()
        print("Troubleshooting:")
        print("  lpb --logs     \u2014 View container logs")
        print("  lpb --stop     \u2014 Stop existing container")
        print("  lpb --remove   \u2014 Remove everything and start fresh")
        sys.exit(1)

    # ── 11. Save last project ────────────────────────────────────────────
    os.makedirs(os.path.dirname(LAST_PROJECT_FILE), exist_ok=True)
    with open(LAST_PROJECT_FILE, "w") as f:
        f.write(project_dir)

    # ── 12. Interactive mode: exec into container ────────────────────────
    if cfg.interactive:
        info(f"\nEntering interactive shell in {cfg.container_name}...")
        print()
        run_cmd([cfg.container_cmd, "exec", "-it", cfg.container_name, "/bin/bash"])
        return

    # ── 13. Health check (wait for VSCodium server) ──────────────────────
    health_url = _build_url()
    info("Waiting for editor to be ready...")
    ready = False
    for _ in range(60):
        try:
            r = subprocess.run(
                ["curl", "-sf", "--max-time", "3", health_url],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                ready = True
                break
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(1)
    print()  # newline after dots

    if ready:
        print()
        info(f"\u2713 Devstack ready at {health_url}")
        print()
        info("  lpb --logs     \u2014 View logs")
        info("  lpb --stop     \u2014 Stop")
        info("  lpb --remove   \u2014 Remove everything")
        info("  lpb            \u2014 Reconnect to last project")
    else:
        print()
        info("⚠ Container is running but the editor may not be ready yet.")
        print()
        info("  Check logs:       lpb --logs")
        info(f"  Container status: {cfg.container_cmd} ps --filter name={cfg.container_name}")
        info("  Stop container:   lpb --stop")
        info("  Remove & restart: lpb --remove")
        print()
        info("  Common issues:")
        info(f"    - Port {cfg.port} already in use \u2192 use --port <new-port>")
        info("    - Container start failed \u2192 check lpb --logs")
        info("    - SELinux blocking mounts \u2192 try running on a filesystem that supports it")


# ─── Entry point ─────────────────────────────────────────────────────────────

parse_cli(sys.argv[1:])
apply_overrides(cfg.project_dir, cfg.project_name)

handlers = {
    "help": cmd_help,
    "stop": cmd_stop,
    "remove": cmd_remove,
    "logs": cmd_logs,
    "update": cmd_update,
    "config": cmd_config,
    "run": cmd_run,
}

handlers.get(cfg.command, cmd_run)()

