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
_cli_overrides = {}


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
    """Ensure cfg.container_cmd is set by finding podman or docker on PATH."""
    if cfg.container_cmd:
        return
    cfg.container_cmd = shutil.which("podman") or shutil.which("docker") or ""
    if not cfg.container_cmd:
        err("podman or docker is required",
            "Install one of them and retry. See https://podman.io or https://docs.docker.com")
        sys.exit(1)

def is_podman():
    """Return True if the detected container engine is podman."""
    return "podman" in cfg.container_cmd


# ─── Container client (SDK-like wrapper around podman/docker CLI) ─────────────
# Provides object-oriented methods for container lifecycle without requiring
# pip install. Only needs the podman or docker CLI binary on PATH.

class ContainerClient:
    """Thin wrapper around podman/docker CLI providing SDK-like methods.

    Methods mirror docker-py / podman-py conventions:
      client.containers.list(all=False)  → ["name1", "name2"]
      client.containers.run(image, ...)  → container_id
      client.containers.stop(name)       → True
      client.containers.remove(name)     → True
      client.images.pull(name)           → (stdout, stderr, rc)
      client.images.exists(name)         → True/False

    Usage:
        client = ContainerClient("podman")  # or "docker"
    """

    def __init__(self, cmd):
        """Initialize with the container CLI binary name."""
        self.cmd = cmd

    # ── Container queries ────────────────────────────────────────────────

    def containers_list(self, all=False):
        """Return list of container names.

        Args:
            all: If True, include stopped containers.

        Returns:
            List of container name strings.
        """
        args = [self.cmd, "ps", "--format", "{{.Names}}"]
        if all:
            args.insert(2, "-a")
        out, _, rc = run_cmd(args)
        return [n.strip() for n in out.strip().splitlines() if n.strip()] if rc == 0 else []

    def container_exists(self, name):
        """Check if a container (running or stopped) exists by name."""
        return name in self.containers_list(all=True)

    def container_running(self, name):
        """Check if a container is currently running."""
        return name in self.containers_list()

    # ── Container lifecycle ──────────────────────────────────────────────

    def containers_run(self, image, name=None, network="host", env=None,
                       volumes=None, userns=None, detach=True, tty=False,
                       interactive=False, command=None, port_bindings=None):
        """Start a container, similar to docker-py's ContainerManager.run().

        Args:
            image:   Image name (e.g. "myimage:latest")
            name:    Container name
            network: Network mode (default: "host")
            env:     List of "KEY=VALUE" environment variables
            volumes: List of "host:container:flags" mount strings
            userns:  User namespace flag (e.g. "keep-id" for podman)
            detach:  Run in background (default: True)
            tty:     Allocate TTY
            interactive: Interactive mode (-i flag)
            command: Override default command
            port_bindings: Dict of {container_port: host_port}

        Returns:
            (container_id, stdout, stderr, rc)
        """
        args = [self.cmd, "run"]
        if detach:
            args.append("-d")

        if name:
            args += ["--name", name]
        args += ["--network", network]

        if userns:
            args += ["--userns", userns]
        if tty:
            args.append("-t")
        if interactive:
            args.append("-i")

        for e in (env or []):
            args += ["-e", str(e)]

        for v in (volumes or []):
            args += ["-v", str(v)]

        for cp, hp in (port_bindings or {}).items():
            args += ["-p", f"{hp}:{cp}"]

        if command:
            if isinstance(command, list):
                args += command
            else:
                args.append(command)
        else:
            args.append(image)

        stdout, stderr, rc = run_cmd(args)
        container_id = stdout.strip()
        return (container_id, stdout, stderr, rc)

    def containers_stop(self, name, timeout=30):
        """Stop a running container.

        Returns:
            True if stopped successfully.
        """
        _, _, rc = run_cmd([self.cmd, "stop", "-t", str(timeout), name])
        return rc == 0

    def containers_remove(self, name, force=True):
        """Remove a container.

        Returns:
            True if removed successfully.
        """
        args = [self.cmd, "rm"]
        if force:
            args.append("-f")
        args.append(name)
        _, _, rc = run_cmd(args)
        return rc == 0

    def containers_exec(self, name, command, tty=True, interactive=True):
        """Execute a command inside a running container.

        Unlike other methods this is interactive — output goes to the
        caller's stdout/stderr, so we don't capture it.
        """
        args = [self.cmd, "exec"]
        if tty:
            args.append("-t")
        if interactive:
            args.append("-i")
        args.append(name)
        if isinstance(command, list):
            args += command
        else:
            args.append(command)
        return subprocess.run(args, check=False).returncode

    def containers_logs(self, name, follow=True, tail=None):
        """Follow or retrieve container logs."""
        args = [self.cmd, "logs"]
        if follow:
            args.append("-f")
        if tail:
            args += ["--tail", str(tail)]
        args.append(name)
        _, _, rc = run_cmd(args)
        return rc == 0

    # ── Image operations ─────────────────────────────────────────────────

    def images_pull(self, name):
        """Pull an image.

        Returns:
            (stdout, stderr, rc)
        """
        return run_cmd([self.cmd, "pull", name])

    def images_inspect(self, name):
        """Inspect an image. Returns rc — 0 means present."""
        _, _, rc = run_cmd([self.cmd, "image", "inspect", name])
        return rc

    def images_exists(self, name):
        """Check if an image is available locally."""
        return self.images_inspect(name) == 0

    # ── Version ──────────────────────────────────────────────────────────

    def version(self):
        """Return client version string."""
        _, out, rc = run_cmd([self.cmd, "version", "--format", "{{.Client.Version}}"])
        return out.strip() if rc == 0 else ""


# ─── Convenience helpers ─────────────────────────────────────────────────────

def client():
    """Get a ContainerClient for the configured container engine."""
    return ContainerClient(cfg.container_cmd)

# ─── Path / mount ────────────────────────────────────────────────────────────

def resolve_path(p):
    return os.path.abspath(os.path.expanduser(p).replace("${HOME}", HOME))

def detect_mount_flags(project_dir):
    c = client()
    _, _, stderr, _ = c.containers_run(
        image="alpine:latest",
        name="_lpb_mnt_test",
        detach=True,
        volumes=[f"{project_dir}:/tmp/mnt:Z"],
    )
    c.containers_remove("_lpb_mnt_test")
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

def _apply_env(cli_overrides=None):
    for ek, attr in _ENV_MAP.items():
        val = os.environ.get(ek)
        if val:
            # Skip if this was set via CLI override
            if cli_overrides and attr in cli_overrides:
                continue
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

def apply_overrides(project_dir=None, project_name=None, cli_overrides=None):
    load_config_file()
    _apply_env(cli_overrides)
    if project_dir and os.path.isfile(os.path.join(project_dir, ".env")):
        load_project_env(project_dir)
        _apply_env(cli_overrides)
    if project_name:
        load_project_override(project_name)
        for ek, attr in [("LPB_PROJECT_PORT", "port"), ("LPB_PROJECT_TOKEN", "token"), ("LPB_PROJECT_HOST", "host")]:
            val = os.environ.get(ek)
            if val and (not cli_overrides or attr not in cli_overrides):
                setattr(cfg, attr, int(val) if attr == "port" else val)

# ─── CLI parsing ─────────────────────────────────────────────────────────────

def parse_cli(args):
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--host":
            if i+1 >= len(args): err("--host requires a value"); sys.exit(1)
            cfg.host = args[i+1]; _cli_overrides["host"] = True; i += 2
        elif a == "--port":
            if i+1 >= len(args): err("--port requires a value"); sys.exit(1)
            try: cfg.port = int(args[i+1]); _cli_overrides["port"] = True
            except ValueError: err(f"--port requires an integer, got: {args[i+1]}"); sys.exit(1)
            i += 2
        elif a == "--token":
            if i+1 >= len(args): err("--token requires a value"); sys.exit(1)
            cfg.token = args[i+1]; _cli_overrides["token"] = True; i += 2
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
    c = client()
    if not c.container_running(cfg.container_name):
        info(f"Container '{cfg.container_name}' is not running.")
        sys.exit(0)
    info(f"Stopping {cfg.container_name}...")
    if not c.containers_stop(cfg.container_name):
        err("Failed to stop", "Check: lpb --logs"); sys.exit(1)
    c.containers_remove(cfg.container_name)
    info("Stopped and removed.")

def cmd_remove():
    ensure_container_cmd()
    c = client()
    c.containers_remove(cfg.container_name)
    for d in (cfg.state_dir, cfg.browser_dir):
        if os.path.isdir(resolve_path(d)):
            shutil.rmtree(resolve_path(d), ignore_errors=True)
    info("Removed devstack (container, state dir, browser dir).")

def cmd_logs():
    ensure_container_cmd()
    c = client()
    if not c.container_exists(cfg.container_name):
        err("Container not found", "Run 'lpb --remove' then 'lpb' to start fresh.")
        sys.exit(0)
    if not c.containers_logs(cfg.container_name):
        err("Failed to follow logs"); sys.exit(1)

def cmd_update():
    ensure_container_cmd()
    c = client()
    info(f"Pulling {cfg.image_name}...")
    _, eo, rc = c.images_pull(cfg.image_name)
    if rc != 0: err("Failed to pull image"); sys.exit(1)

def cmd_config():
    info(f"Config file: {CONFIG_FILE}")
    info(f"Projects:    {PROJECTS_DIR}")
    info(f"State dir:   {resolve_path(cfg.state_dir)}")
    info(f"Browser dir: {resolve_path(cfg.browser_dir)}")


# ─── cmd_run ─────────────────────────────────────────────────────────────────

def _get_lan_ips():
    """Return a list of non-loopback IPv4 addresses on this machine.

    Tries multiple methods in order of reliability:
      1. hostname -I (most common)
      2. ip -4 addr show (Linux)
      3. ifconfig (macOS/BSD)
    Only IPv4 addresses are returned.
    """
    ipv4_re = re.compile(r'^(\d+\.\d+\.\d+\.\d+)$')
    ips = []

    # Method 1: hostname -I (Linux, widely available)
    try:
        r = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for addr in r.stdout.split():
                if ipv4_re.match(addr) and not addr.startswith("127."):
                    ips.append(addr)
    except (FileNotFoundError, OSError):
        pass

    if ips:
        return ips

    # Method 2: ip -4 addr show (Linux systemd)
    try:
        r = subprocess.run(
            ["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                m = re.search(r'(?:inet)\s+(\d+\.\d+\.\d+\.\d+)', line)
                if m and not m.group(1).startswith("127."):
                    ips.append(m.group(1))
    except (FileNotFoundError, OSError):
        pass

    if ips:
        return ips

    # Method 3: ifconfig (macOS/BSD)
    try:
        r = subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for m in re.finditer(r'inet\s+(\d+\.\d+\.\d+\.\d+)', r.stdout):
                ip = m.group(1)
                if not ip.startswith("127."):
                    ips.append(ip)
    except (FileNotFoundError, OSError):
        pass

    return ips


def _get_host_for_url():
    """Return the display host for the URL based on cfg.host.

    - host=0.0.0.0 → show first LAN IP
    - host=localhost → show localhost
    - host=127.0.0.1 → show localhost
    - host=<specific IP> → show that IP
    """
    h = cfg.host
    if h in ("0.0.0.0", "::"):
        lan = _get_lan_ips()
        return lan[0] if lan else h
    if h in ("localhost", "127.0.0.1"):
        return h
    return h


def _build_urls():
    """Return a dict of label → URL for all accessible endpoints.

    Examples:
      host=localhost        → {"Local": "http://localhost:8000/..."}
      host=0.0.0.0          → {"Local": "http://localhost:8000/...",
                                 "LAN": "http://192.168.1.5:8000/..."}
      host=192.168.1.100    → {"Server": "http://192.168.1.100:8000/..."}
    """
    host = _get_host_for_url()
    port = cfg.port
    token_part = "" if cfg.without_token else f"?tkn={cfg.token}"
    base = f"http://{host}:{port}/{token_part}"

    urls = {host: base}

    # When binding on 0.0.0.0, also show localhost + each LAN IP
    if cfg.host in ("0.0.0.0", "::"):
        lan_ips = _get_lan_ips()
        localhost_url = f"http://localhost:{port}/{token_part}"
        urls["localhost"] = localhost_url
        for ip in lan_ips:
            lan_url = f"http://{ip}:{port}/{token_part}"
            urls[ip] = lan_url

    return urls


def _build_url():
    """Build the URL to use for the health check.

    Uses cfg.host directly since curl must connect to the address the server
    is actually listening on. Uses 127.0.0.1 (IPv4) instead of localhost to
    avoid IPv6 ::1 resolution failures.
    """
    check_host = cfg.host
    if check_host == "0.0.0.0":
        check_host = "127.0.0.1"  # IPv4 loopback (avoids ::1 IPv6 issues)
    if check_host in ("localhost", "127.0.0.1"):
        check_host = "127.0.0.1"
    port = cfg.port
    token_part = "" if cfg.without_token else f"?tkn={cfg.token}"
    return f"http://{check_host}:{port}/{token_part}"


def cmd_run():
    ensure_container_cmd()
    c = client()
    verbose = cfg.interactive

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

    # ── 4. Show summary (verbose only) ──────────────────────────────────
    if verbose:
        info(f"Devstack: {cfg.project_name}")
        info(f"  Image:    {cfg.image_name}")
        info(f"  Project:  {project_dir} \u2192 {mount_path}")
        display_host = _get_host_for_url()
        info(f"  Editor:   http://{display_host}:{cfg.port}")
        if cfg.without_token:
            info("  Auth:     none (\u26a0 unsecured)")
        else:
            info(f"  Token:    {cfg.token}")
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
    if c.container_running(cfg.container_name):
        if verbose:
            info("Stopping existing devstack container...")
        c.containers_stop(cfg.container_name)

    if not c.images_exists(cfg.image_name):
        if verbose:
            info(f"Pulling {cfg.image_name}...")
        _, eo, rc = c.images_pull(cfg.image_name)
        if rc != 0:
            err("Failed to pull image", eo.strip().splitlines()[-1][:200] if eo.strip() else "")
            sys.exit(1)

    # ── 8. Detect SELinux mount flags ────────────────────────────────────
    mount_flags = detect_mount_flags(project_dir)

    # ── 9. Remove stale stopped containers ───────────────────────────────
    if c.container_exists(cfg.container_name):
        if verbose:
            info(f"Removing stale container '{cfg.container_name}'...")
        c.containers_remove(cfg.container_name)

    # ── 10. Run container via client ─────────────────────────────────────
    if verbose:
        info("Running...")

    env_vars = [
        f"LPB_ED_PORT={cfg.port}",
        f"LPB_EDITOR_HOST={cfg.host}",
        f"LPB_DEVCONTAINER_WORKSPACE_DIR={mount_path}",
        f"LPB_CONNECTION_TOKEN={cfg.token}",
        "LPB_STATE_DIR=/home/dev/.pi",
        # Exa MCP key — stripped by start.sh → EXA_API_KEY
        f"LPB_EXA_API_KEY={os.environ.get('LPB_EXA_API_KEY', os.environ.get('EXA_API_KEY', ''))}",
    ]

    # Agent-browser env vars (passed through so start.sh exports them)
    for k in ("PI_WORKTREE_ID", "LPB_AGENT_BROWSER_ARGS",
              "LPB_AGENT_BROWSER_MAX_OUTPUT", "LPB_AGENT_BROWSER_CONTENT_BOUNDARIES",
              "LPB_AGENT_BROWSER_CONFIRM_ACTIONS", "LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS",
              "LPB_AGENT_BROWSER_SESSION"):
        val = os.environ.get(k)
        if val:
            env_vars.append(f"{k}={val}")
    volumes = [
        f"{project_dir}:{mount_path}{mount_flags}",
        f"{resolved_state}:/home/dev/.pi{mount_flags}",
        f"{dir_browser}:/home/dev/.agent-browser{mount_flags}",
    ]
    userns = "keep-id" if is_podman() else None

    container_id, stdout, stderr, rc = c.containers_run(
        image=cfg.image_name,
        name=cfg.container_name,
        network="host",
        env=env_vars,
        volumes=volumes,
        userns=userns,
        interactive=cfg.interactive,
        detach=True,
    )

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
        c.containers_exec(cfg.container_name, "/bin/bash")
        return

    # ── 13. Health check (shorter timeout for non-interactive) ───────────
    health_url = _build_url()
    ready = False
    timeout = 60 if verbose else 30
    try:
        for _ in range(timeout):
            try:
                r = subprocess.run(
                    ["curl", "-sf", "--max-time", "2", health_url],
                    capture_output=True, timeout=5,
                )
                if r.returncode == 0:
                    ready = True
                    break
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
            if verbose:
                sys.stdout.write(".")
                sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        info("Aborted.")
        sys.exit(130)
    if verbose:
        print()

    if ready:
        if verbose:
            urls = _build_urls()
            if len(urls) == 1:
                label, url = list(urls.items())[0]
                info(f"\u2713 Devstack ready at {url}")
            else:
                items = list(urls.items())
                info(f"\u2713 Devstack ready")
                for label, url in items:
                    if label == "localhost" or label.startswith("127."):
                        info(f"    Local:   {url}")
                    else:
                        info(f"    LAN:     {url}")
            print()
            info("  lpb --logs     \u2014 View logs")
            info("  lpb --stop     \u2014 Stop")
            info("  lpb --remove   \u2014 Remove everything")
            info("  lpb            \u2014 Reconnect to last project")
        else:
            label, url = list(_build_urls().items())[0]
            info(f"{cfg.project_name} ready at {url}")
    else:
        if verbose:
            print()
            info("\u26a0 Container is running but the editor may not be ready yet.")
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
        else:
            info(f"{cfg.container_name} started (editor may still be booting)")


# ─── Entry point ─────────────────────────────────────────────────────────────

parse_cli(sys.argv[1:])
apply_overrides(cfg.project_dir, cfg.project_name, _cli_overrides)

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

