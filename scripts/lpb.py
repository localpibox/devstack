#!/usr/bin/env python3
"""lpb - LocalPibox Devstack launcher

Usage:
    lpb [/path/to/project]              Start Pi CLI session at project (foreground)
    lpb --shell [/path/to/project]      Start interactive bash shell in container
    lpb --web [/path/to/project]        Start VSCodium at project (background)
    lpb --stop                          Stop the container
    lpb --remove                        Stop + remove container + state dirs
    lpb --logs                          Stream container logs
    lpb --update                        Pull latest image(s)
    lpb --config                        Show config file location
    lpb --help                          Show usage

VSCodium options (before project path, --web mode only):
    --host <HOST>          Host to listen on (default: from .env or localhost)
    --port <PORT>          Port to listen on (default: from .env or 8000)
    --token <TOKEN>        Connection token (default: from .env or devsession)
    --without-token        Disable auth (trusted networks only!)
    --data-dir <PATH>      Server data directory
    --user-data-dir <PATH> User data directory (multiple instances)
    --ext-dir <PATH>       Extensions root path
    --base-path <PATH>     Web UI subpath (e.g. /ide)

Examples:
    lpb                                         Start Pi CLI session at ~
    lpb /home/user/myproject                    Start Pi CLI session at project
    lpb --shell /home/user/myproject            Interactive bash in container
    lpb --web                                   Open VSCodium at ~ (user picks project)
    lpb --web /home/user/myproject              Open VSCodium at project
    lpb --web --port 8080                       Custom port for VSCodium
    lpb --without-token                         No auth (localhost only!)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".localpibox", "devstack")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config")
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
LAST_PROJECT_FILE = os.path.join(CONFIG_DIR, "last-project")
LAST_IMAGE_FILE = os.path.join(CONFIG_DIR, "last-image")

CLI_IMAGE = "ghcr.io/localpibox/devstack:cli"
WEB_IMAGE = "ghcr.io/localpibox/devstack:web"


class Config:
    image_name = CLI_IMAGE
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
    command = "run"
    web_mode = False
    shell_mode = False


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
    if cfg.container_cmd:
        return
    cfg.container_cmd = shutil.which("podman") or shutil.which("docker") or ""
    if not cfg.container_cmd:
        err("podman or docker is required", "Install one of them and retry.")
        sys.exit(1)


def is_podman():
    return "podman" in cfg.container_cmd


def save_last_image(mode):
    os.makedirs(os.path.dirname(LAST_IMAGE_FILE), exist_ok=True)
    with open(LAST_IMAGE_FILE, "w") as f:
        f.write(mode)


def load_last_image():
    if os.path.isfile(LAST_IMAGE_FILE):
        with open(LAST_IMAGE_FILE) as f:
            return f.read().strip()
    return "cli"


class ContainerClient:
    def __init__(self, cmd):
        self.cmd = cmd

    def containers_list(self, all=False):
        args = [self.cmd, "ps", "--format", "{{.Names}}"]
        if all:
            args.insert(2, "-a")
        out, _, rc = run_cmd(args)
        return [n.strip() for n in out.strip().splitlines() if n.strip()] if rc == 0 else []

    def container_exists(self, name):
        return name in self.containers_list(all=True)

    def container_running(self, name):
        return name in self.containers_list()

    def containers_run(self, image, name=None, network="host", env=None,
                       volumes=None, userns=None, detach=True, tty=False,
                       interactive=False, command=None, port_bindings=None):
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
            args += command if isinstance(command, list) else [command]
        else:
            args.append(image)
        stdout, stderr, rc = run_cmd(args)
        return (stdout.strip(), stdout, stderr, rc)

    def containers_stop(self, name, timeout=30):
        _, _, rc = run_cmd([self.cmd, "stop", "-t", str(timeout), name])
        return rc == 0

    def containers_remove(self, name, force=True):
        args = [self.cmd, "rm"]
        if force:
            args.append("-f")
        args.append(name)
        _, _, rc = run_cmd(args)
        return rc == 0

    def containers_exec(self, name, command, tty=True, interactive=True):
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
        args = [self.cmd, "logs"]
        if follow:
            args.append("-f")
        if tail:
            args += ["--tail", str(tail)]
        args.append(name)
        _, _, rc = run_cmd(args)
        return rc == 0

    def images_pull(self, name):
        """Pull image with full verbosity and no timeout (like native podman/docker pull)."""
        return subprocess.run(
            [self.cmd, "pull", name],
            stdout=sys.stdout, stderr=sys.stderr, stdin=sys.stdin,
            check=False
        ).returncode

    def images_inspect(self, name):
        _, _, rc = run_cmd([self.cmd, "image", "inspect", name])
        return rc

    def images_exists(self, name):
        return self.images_inspect(name) == 0

    def version(self):
        _, out, rc = run_cmd([self.cmd, "version", "--format", "{{.Client.Version}}"])
        return out.strip() if rc == 0 else ""


def client():
    return ContainerClient(cfg.container_cmd)


def resolve_path(p):
    return os.path.abspath(os.path.expanduser(p).replace("${HOME}", HOME))


def detect_mount_flags(project_dir):
    c = client()
    _, _, stderr, _ = c.containers_run(
        image="alpine:latest", name="_lpb_mnt_test", detach=True,
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
        for ek, attr in [("LPB_PROJECT_PORT", "port"), ("LPB_PROJECT_TOKEN", "token"),
                         ("LPB_PROJECT_HOST", "host")]:
            val = os.environ.get(ek)
            if val and (not cli_overrides or attr not in cli_overrides):
                setattr(cfg, attr, int(val) if attr == "port" else val)


# ─── CLI parsing ─────────────────────────────────────────────────────────────

HELP = (
    "lpb — LocalPibox Devstack launcher\n\n"
    "Usage:\n"
    "  lpb [/path/to/project]           Start Pi CLI session at project\n"
    "  lpb --shell [/path/to/project]   Interactive bash shell in container\n"
    "  lpb --web [/path/to/project]     Start VSCodium (background)\n"
    "  lpb --stop                       Stop the container\n"
    "  lpb --remove                     Stop + remove container + state dirs\n"
    "  lpb --logs                       Stream container logs\n"
    "  lpb --update                     Pull latest image(s)\n"
    "  lpb --config                     Show config file location\n"
    "  lpb --help                       Show this help\n\n"
    "VSCodium options (--web mode only):\n"
    "  --host <HOST>          Host to listen on (default: localhost)\n"
    "  --port <PORT>          Port (default: from .env or 8000)\n"
    "  --token <TOKEN>        Connection token (default: devsession)\n"
    "  --without-token        Disable auth (localhost only!)\n\n"
    "Examples:\n"
    "  lpb /path/to/project                    Start Pi CLI at project\n"
    "  lpb --shell /path/to/project            Bash shell in container\n"
    "  lpb --web /path/to/project              Open VSCodium at project\n"
    "  lpb --web --port 8080                   Custom VSCodium port\n"
    "  lpb --without-token                     No auth (localhost only!)"
)


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
            try:
                cfg.port = int(args[i+1]); _cli_overrides["port"] = True
            except ValueError:
                err(f"--port requires an integer, got: {args[i+1]}"); sys.exit(1)
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
        elif a == "--shell":
            cfg.shell_mode = True; i += 1
        elif a == "--web":
            cfg.web_mode = True; i += 1
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


def cmd_help():
    print(HELP); sys.exit(0)


def cmd_stop():
    ensure_container_cmd()
    c = client()
    if not c.container_running(cfg.container_name):
        info(f"Container '{cfg.container_name}' is not running."); sys.exit(0)
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


def cmd_config():
    info(f"Config file: {CONFIG_FILE}")
    info(f"Projects:    {PROJECTS_DIR}")
    info(f"State dir:   {resolve_path(cfg.state_dir)}")


def cmd_update():
    ensure_container_cmd()
    c = client()
    # Determine which image(s) to update based on what's locally available
    last_img = load_last_image()
    images_to_update = []
    if c.images_exists(CLI_IMAGE):
        images_to_update.append(CLI_IMAGE)
    if c.images_exists(WEB_IMAGE):
        images_to_update.append(WEB_IMAGE)
    if not images_to_update:
        # Fall back to the last used image
        if c.images_exists(last_img):
            images_to_update.append(last_img)
        else:
            err("No devstack images found locally", "Run 'lpb' or 'lpb --web' first to pull an image.")
            sys.exit(1)
    for img in images_to_update:
        info(f"Pulling {img}...")
        rc = c.images_pull(img)
        if rc != 0:
            err(f"Failed to pull {img}")


def _get_lan_ips():
    ipv4_re = re.compile(r'^(\d+\.\d+\.\d+\.\d+)$')
    ips = []
    try:
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for addr in r.stdout.split():
                if ipv4_re.match(addr) and not addr.startswith("127."):
                    ips.append(addr)
    except (FileNotFoundError, OSError):
        pass
    if ips:
        return ips
    try:
        r = subprocess.run(["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                m = re.search(r'(?:inet)\s+(\d+\.\d+\.\d+\.\d+)', line)
                if m and not m.group(1).startswith("127."):
                    ips.append(m.group(1))
    except (FileNotFoundError, OSError):
        pass
    if ips:
        return ips
    try:
        r = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for m in re.finditer(r'inet\s+(\d+\.\d+\.\d+\.\d+)', r.stdout):
                ip = m.group(1)
                if not ip.startswith("127."):
                    ips.append(ip)
    except (FileNotFoundError, OSError):
        pass
    return ips


def _get_host_for_url():
    h = cfg.host
    if h in ("0.0.0.0", "::"):
        lan = _get_lan_ips()
        return lan[0] if lan else h
    if h in ("localhost", "127.0.0.1"):
        return h
    return h


def _build_urls():
    host = _get_host_for_url()
    port = cfg.port
    token_part = "" if cfg.without_token else f"?tkn={cfg.token}"
    base = f"http://{host}:{port}/{token_part}"
    urls = {host: base}
    if cfg.host in ("0.0.0.0", "::"):
        localhost_url = f"http://localhost:{port}/{token_part}"
        urls["localhost"] = localhost_url
        for ip in _get_lan_ips():
            urls[ip] = f"http://{ip}:{port}/{token_part}"
    return urls


def _build_url():
    check_host = cfg.host
    if check_host in ("0.0.0.0", "localhost", "127.0.0.1"):
        check_host = "127.0.0.1"
    port = cfg.port
    token_part = "" if cfg.without_token else f"?tkn={cfg.token}"
    return f"http://{check_host}:{port}/{token_part}"


def cmd_run():
    ensure_container_cmd()
    c = client()

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
        err(f"directory not found: {project_dir}"); sys.exit(1)

    # ── 2. Project name ──────────────────────────────────────────────────
    cfg.project_name = os.path.basename(project_dir)
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$', cfg.project_name):
        err(f"project name '{cfg.project_name}' contains invalid characters",
            "Use only alphanumeric, dots, hyphens, underscores.")
        sys.exit(1)

    # ── 3. Mount path inside container ───────────────────────────────────
    if cfg.open_home:
        mount_path = "/home/dev/workspace"
    else:
        mount_path = f"/home/dev/workspace/{cfg.project_name}"

    # ── 4. Determine image and mode ──────────────────────────────────────
    if cfg.web_mode:
        cfg.image_name = WEB_IMAGE
        mode_label = "web (VSCodium)"
    elif cfg.shell_mode:
        cfg.image_name = CLI_IMAGE
        mode_label = "cli (shell)"
    else:
        cfg.image_name = CLI_IMAGE
        mode_label = "cli (Pi CLI)"

    # ── 5. Show summary ─────────────────────────────────────────────────
    info(f"Devstack: {cfg.project_name} ({mode_label})")
    info(f"  Image:    {cfg.image_name}")
    info(f"  Project:  {project_dir} \u2192 {mount_path}")
    info("")

    # ── 6. Resolve & ensure state dirs ───────────────────────────────────
    resolved_state = resolve_path(cfg.state_dir)
    dir_browser = resolve_path(cfg.browser_dir)
    os.makedirs(resolved_state, exist_ok=True)
    os.makedirs(dir_browser, exist_ok=True)

    # ── 7. Stop existing container ───────────────────────────────────────
    if c.container_running(cfg.container_name):
        info("Stopping existing devstack container...")
        c.containers_stop(cfg.container_name)

    # ── 8. Pull image if needed ──────────────────────────────────────────
    if not c.images_exists(cfg.image_name):
        info(f"Pulling {cfg.image_name}...")
        rc = c.images_pull(cfg.image_name)
        if rc != 0:
            err("Failed to pull image")
            sys.exit(1)

    # ── 9. Detect SELinux mount flags ────────────────────────────────────
    mount_flags = detect_mount_flags(project_dir)

    # ── 10. Remove stale stopped containers ──────────────────────────────
    if c.container_exists(cfg.container_name):
        info(f"Removing stale container '{cfg.container_name}'...")
        c.containers_remove(cfg.container_name)

    # ── 11. Build env vars and volumes ───────────────────────────────────
    env_vars = [
        f"LPB_ED_PORT={cfg.port}",
        f"LPB_EDITOR_HOST={cfg.host}",
        f"LPB_DEVCONTAINER_WORKSPACE_DIR={mount_path}",
        f"LPB_CONNECTION_TOKEN={cfg.token}",
        "LPB_STATE_DIR=/home/dev/.pi",
        f"LPB_EXA_API_KEY={os.environ.get('LPB_EXA_API_KEY', os.environ.get('EXA_API_KEY', ''))}",
    ]
    for k in ("PI_WORKTREE_ID", "LPB_AGENT_BROWSER_ARGS", "LPB_AGENT_BROWSER_MAX_OUTPUT",
              "LPB_AGENT_BROWSER_CONTENT_BOUNDARIES", "LPB_AGENT_BROWSER_CONFIRM_ACTIONS",
              "LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS", "LPB_AGENT_BROWSER_SESSION"):
        val = os.environ.get(k)
        if val:
            env_vars.append(f"{k}={val}")

    volumes = [
        f"{project_dir}:{mount_path}{mount_flags}",
        f"{resolved_state}:/home/dev/.pi{mount_flags}",
        f"{dir_browser}:/home/dev/.agent-browser{mount_flags}",
    ]
    # ── 12. Mount gh config (persisted across restarts) ──────────────────
    gh_config = resolve_path(os.path.join(cfg.state_dir, "gh-config"))
    os.makedirs(gh_config, exist_ok=True)
    volumes.append(f"{gh_config}:/home/dev/.config/gh{mount_flags}")

    userns = "keep-id" if is_podman() else None

    # ── 12. Run container ────────────────────────────────────────────────
    if cfg.web_mode:
        # Web mode: background, health check
        info("Starting VSCodium server (background)...")
        container_id, stdout, stderr, rc = c.containers_run(
            image=cfg.image_name, name=cfg.container_name, network="host",
            env=env_vars, volumes=volumes, userns=userns, detach=True,
        )
        if rc != 0 or not container_id:
            err("failed to start container")
            if stderr: print(stderr, file=sys.stderr)
            print("\nTroubleshooting:")
            print("  lpb --logs     \u2014 View container logs")
            print("  lpb --stop     \u2014 Stop existing container")
            print("  lpb --remove   \u2014 Remove everything and start fresh")
            sys.exit(1)

        os.makedirs(os.path.dirname(LAST_PROJECT_FILE), exist_ok=True)
        with open(LAST_PROJECT_FILE, "w") as f:
            f.write(project_dir)
        save_last_image("web")

        # Health check
        health_url = _build_url()
        ready = False
        try:
            for _ in range(30):
                try:
                    r = subprocess.run(["curl", "-sf", "--max-time", "2", health_url],
                                       capture_output=True, timeout=5)
                    if r.returncode == 0:
                        ready = True; break
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                    pass
                sys.stdout.write("."); sys.stdout.flush()
                time.sleep(1)
        except KeyboardInterrupt:
            print(); info("Aborted."); sys.exit(130)
        print()

        if ready:
            urls = _build_urls()
            for label, url in urls.items():
                info(f"\u2713 Devstack ready at {url}")
            info("\n  lpb --logs     \u2014 View logs")
            info("  lpb --stop     \u2014 Stop")
            info("  lpb --remove   \u2014 Remove everything")
            info("  lpb            \u2014 Reconnect to last project")
        else:
            info("\u26a0 Container running but editor may not be ready yet.")
            info("  Check logs:       lpb --logs")
            info(f"  Container status: {cfg.container_cmd} ps --filter name={cfg.container_name}")
    else:
        # CLI / shell mode: foreground, stop on exit
        info("Starting container (foreground)...\n")
        # Save last-project for reconnection
        os.makedirs(os.path.dirname(LAST_PROJECT_FILE), exist_ok=True)
        with open(LAST_PROJECT_FILE, "w") as f:
            f.write(project_dir)
        save_last_image("cli")
        # Run foreground, then stop container after exit
        args = [cfg.container_cmd, "run", "--rm", "--network", "host"]
        if is_podman():
            args += ["--userns", "keep-id"]
        args += ["-i", "-t", "--name", cfg.container_name]
        for e in env_vars:
            args += ["-e", str(e)]
        for v in volumes:
            args += ["-v", str(v)]
        args.append(cfg.image_name)
        ret = subprocess.run(args, check=False).returncode
        # Container is removed (--rm), nothing to clean up


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
