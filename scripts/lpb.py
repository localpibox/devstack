#!/usr/bin/env python3
"""lpb - LocalPibox Devstack launcher

Usage:
    lpb [/path/to/project]              Start Pi CLI session at project (foreground)
    lpb /path -- <pi-args...>           Pass args through to pi (e.g. -p, --session)
    lpb --shell [/path/to/project]      Start interactive bash shell in container
    lpb --ssh [pubkey|path] [/path]     Start sshd server (background) for remote login
    lpb --web [/path/to/project]        Start VSCodium at project (background)
    lpb --stop                          Stop the container
    lpb --remove                        Stop + remove container + state dirs
    lpb --logs                          Stream container logs
    lpb --update                        Pull latest image(s)
    lpb --config                        Show config file location
    lpb --help                          Show usage
    lpb --tag dev|main|latest           Select image pipeline (dev/main/latest/<custom>)

Positional command aliases (no -- needed):
    lpb logs     → lpb --logs
    lpb stop     → lpb --stop
    lpb update   → lpb --update
    lpb remove   → lpb --remove
    lpb config   → lpb --config
    lpb version  → lpb --version
    lpb help     → lpb --help

Image tag selection:
    lpb --tag dev                      Use latest dev image (0.0.x-lpb-dev-cli)
    lpb --tag main                     Use latest stable image (0.0.x-lpb-cli)
    lpb --tag latest                   Same as main
    lpb --tag 0.0.9-lpb-dev            Pin to specific version image
    LPB_IMAGE_TAG=0.0.9-lpb-dev        Or set env var for persistent override

Pi passthrough (after "--"):
    lpb /myproject -- -p "summarize this repo"
    lpb /myproject -- --session abc123
    lpb /myproject -- --continue
    lpb /myproject -- --mode json -p "analyze"
    lpb /myproject -- --thinking high --name "feature-x"

VSCodium options (before project path, --web mode only):
    --host <HOST>          Host to listen on (default: from .env or localhost)
    --port <PORT>          Port to listen on (default: from .env or 3000)
    --token <TOKEN>        Connection token (default: auto-generated)
    --new-token            Generate a fresh token (ignore persisted one)
    --without-token        Disable auth in URL display (server still requires auth)
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
    lpb --without-token                         Hide token in URL display
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid
import socket
from pathlib import Path

# ── Structured logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger()

# ── Custom exceptions ─────────────────────────────────────────────────────────
class DevstackError(Exception):
    """Raised when a devstack operation fails (e.g. missing container, invalid config)."""

class DevstackConfigError(DevstackError):
    """Raised when configuration is invalid (e.g. missing files, bad env vars)."""

HOME = os.path.expanduser("~")
CONFIG_DIR = Path(HOME) / ".localpibox" / "devstack"
CONFIG_FILE = CONFIG_DIR / "config"
PROJECTS_DIR = CONFIG_DIR / "projects"
LAST_PROJECT_FILE = CONFIG_DIR / "last-project"
LAST_VERSION_FILE = CONFIG_DIR / "last-version"
TOKEN_FILE = CONFIG_DIR / "token"

# ─── Load stack configuration ────────────────────────────────────────────
# lpb.stack.env defines build/image identity (fork URL, images, container)
# Loaded as fallback defaults; shell env / .env override takes priority.
def _find_env_file(name: str) -> Path | None:
    """Locate an env file (lpb.stack.env / lpb.conf.env).

    Search order (first match wins):
      1. Next to this script (installed layout: ~/.local/bin/)
      2. Repo root (scripts/lpb.py run from a git checkout)
      3. CONFIG_DIR (host install copy)
    """
    candidates = [
        Path(__file__).parent / name,
        Path(__file__).parent.parent / name,
        CONFIG_DIR / name,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value lines (optional export prefix), stripping quotes."""
    env: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'(?:(?:export\s+)?(\w+))=(.*)', line)
                if m:
                    env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _load_stack_env() -> dict[str, str]:
    """Load lpb.stack.env (build/image identity)."""
    stack_env = _find_env_file("lpb.stack.env")
    return _parse_env_file(stack_env) if stack_env else {}

_stack_cfg = _load_stack_env()

CLI_IMAGE = _stack_cfg.get("LPB_IMAGE_CLI", "ghcr.io/localpibox/devstack:cli")
WEB_IMAGE = _stack_cfg.get("LPB_IMAGE_WEB", "ghcr.io/localpibox/devstack:web")

# ─── Default image tag from env var ──────────────────────────────────
# Users can set LPB_IMAGE_TAG=dev in their environment for persistent override.
cfg_image_tag = os.environ.get("LPB_IMAGE_TAG", "")


# ─── Version resolution (dev/main pipeline) ───────────────────────────
# The image is built with version tags (e.g. 0.0.9-lpb-dev-cli).
# --tag dev/main resolves to the latest versioned image for that pipeline.
def _load_last_version() -> str:
    """Load the last-used version tag."""
    if LAST_VERSION_FILE.is_file():
        with open(LAST_VERSION_FILE) as f:
            return f.read().strip()
    return ""


def _get_remote_version(branch: str = "dev") -> str:
    """Fetch the latest VERSION from the remote branch."""
    try:
        url = f"https://raw.githubusercontent.com/localpibox/devstack/{branch}/VERSION"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.read().decode().strip()
    except Exception:
        return ""


def _save_version(version: str) -> None:
    """Persist the version tag for reconnection/update (only valid versioned tags)."""
    # Only persist tags that match the version pattern (0.0.x-lpb[-dev]), not legacy :cli/:web
    if not re.match(r'^0\.0\.\d+-lpb(-dev)?$', version):
        return
    LAST_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_VERSION_FILE, "w") as f:
        f.write(version)


# ── Backwards-compat aliases (mutation tests expect these names) ─────
save_last_version = _save_version
load_last_version = _load_last_version


def _resolve_version_image(version: str, mode: str) -> str:
    """Resolve the full image name from a version tag.
    
    Args:
        version: Version tag (e.g. 0.0.9-lpb-dev, 0.0.9-lpb)
        mode: 'cli' or 'web'
    
    Returns:
        Full image name (e.g. ghcr.io/localpibox/devstack:0.0.9-lpb-dev-cli)
    """
    return f"ghcr.io/localpibox/devstack:{version}-{mode}"


def resolve_cli_image(tag: str) -> str:
    """Resolve the final CLI image name from stack config + tag override.
    
    --tag dev/main → latest versioned image (0.0.x-lpb[-dev]-cli)
    --tag <custom> → :<custom>-cli (explicit version)
    """
    if not tag:
        last = _load_last_version()
        if last:
            return _resolve_version_image(last, "cli")
        return CLI_IMAGE  # fallback
    
    if tag == "dev":
        version = _load_last_version()
        if not version:
            version = _get_remote_version("dev")
        if not version:
            version = "0.0.0-lpb"  # last resort
        return _resolve_version_image(version if "-dev" in version else version + "-dev", "cli")
    
    if tag == "main" or tag == "latest":
        version = _load_last_version() or "0.0.0-lpb"
        return _resolve_version_image(version.replace("-dev", ""), "cli")
    
    # Custom/explicit version tag
    return _resolve_version_image(tag, "cli")


def resolve_web_image(tag: str) -> str:
    """Resolve the final WEB image name from stack config + tag override."""
    if not tag:
        last = _load_last_version()
        if last:
            return _resolve_version_image(last, "web")
        return WEB_IMAGE
    
    if tag == "dev":
        version = _load_last_version()
        if not version:
            version = _get_remote_version("dev")
        if not version:
            version = "0.0.0-lpb"
        return _resolve_version_image(version if "-dev" in version else version + "-dev", "web")
    
    if tag == "main" or tag == "latest":
        version = _load_last_version()
        if not version:
            version = _get_remote_version("main")
        if not version:
            version = "0.0.0-lpb"
        return _resolve_version_image(version.replace("-dev", ""), "web")
    
    # Custom/explicit version tag
    return _resolve_version_image(tag, "web")


# ─── Load runtime configuration ──────────────────────────────────────────
# lpb.conf.env defines runtime defaults (editor, browser, LLM, persistence)
# Loaded after stack env — workspace .env overrides both.
def _load_conf_env() -> dict[str, str]:
    """Load lpb.conf.env (runtime defaults)."""
    conf_env = _find_env_file("lpb.conf.env")
    return _parse_env_file(conf_env) if conf_env else {}

_conf_cfg = _load_conf_env()


class Config:
    image_name = CLI_IMAGE
    image_tag = cfg_image_tag  # dev, main, latest, or custom tag suffix
    container_name = _stack_cfg.get("LPB_CONTAINER_NAME", "localpibox")
    container_cmd = ""
    port = int(os.environ.get("ED_PORT", os.environ.get("LPB_ED_PORT", _conf_cfg.get("LPB_ED_PORT", "3000"))))
    host = os.environ.get("LPB_EDITOR_HOST", os.environ.get("HOST", _conf_cfg.get("LPB_EDITOR_HOST", "localhost")))
    token = os.environ.get("LPB_CONNECTION_TOKEN", os.environ.get("CONNECTION_TOKEN", ""))
    # codium-server always requires auth — always generate/use a token
    # (--without-token flag only affects URL display, not server behavior)
    # (--new-token flag forces a fresh token instead of reusing persisted one)
    without_token = False
    new_token = False
    state_dir = os.environ.get("LPB_STATE_DIR", _conf_cfg.get("LPB_STATE_DIR", str(Path(HOME) / ".localpibox" / "state")))
    browser_dir = os.environ.get("LPB_BROWSER_DIR", _conf_cfg.get("LPB_BROWSER_DIR", str(Path(HOME) / ".localpibox" / "agent-browser")))
    project_dir = ""
    project_name = ""
    open_home = False
    command = "run"
    web_mode = False
    shell_mode = False
    ssh_mode = False
    ssh_pubkey = ""
    ssh_port = os.environ.get("LPB_SSH_PORT", _conf_cfg.get("LPB_SSH_PORT", "2222"))
    pi_args = []  # args after "--" forwarded to pi inside container


cfg = Config()
_ERR, _WRN, _RSV = "\033[31m", "\033[33m", "\033[0m"
_cli_overrides = {}


def err(msg: str, hint: str = "") -> None:
    """Print an error (red) to stderr; optionally with a yellow hint line."""
    logger.error("%sError: %s%s", _ERR, msg, _RSV)
    print(f"{_ERR}Error: {msg}{_RSV}", file=sys.stderr)
    if hint:
        logger.warning("  %s%s%s", _WRN, hint, _RSV)
        print(f"  {_WRN}{hint}{_RSV}", file=sys.stderr)


def warn(msg: str) -> None:
    """Print a warning (yellow) to stderr."""
    logger.warning("%sWarning: %s%s", _WRN, msg, _RSV)
    print(f"{_WRN}Warning: {msg}{_RSV}", file=sys.stderr)


# ── Output helpers (stdout) ───────────────────────────────────────────────────

def self_update() -> None:
    """Update lpb itself from the GitHub repo if a newer version is available."""
    lpb_path = Path(sys.argv[0]).resolve()
    lpb_dir = lpb_path.parent
    new_path = lpb_dir / "lpb.new"
    if not lpb_path.is_file():
        return
    # Select branch based on cfg.image_tag (set by --tag)
    branch = "dev" if cfg.image_tag == "dev" else "main"
    script_url = f"https://raw.githubusercontent.com/localpibox/devstack/{branch}/scripts/lpb"
    py_url = script_url.replace("/lpb", "/lpb.py")
    try:
        with urllib.request.urlopen(script_url, timeout=10) as resp:
            new_wrapper = resp.read()
        with open(lpb_path, "rb") as f:
            old_wrapper = f.read()
        if new_wrapper != old_wrapper:
            info(f"Updating lpb launcher...")
            with open(new_path, "wb") as f:
                f.write(new_wrapper)
            new_path.rename(lpb_path)
            lpb_path.chmod(0o755)
        with urllib.request.urlopen(py_url, timeout=10) as resp:
            new_py = resp.read()
        py_path = lpb_dir / "lpb.py"
        if py_path.is_file():
            with open(py_path, "rb") as f:
                old_py = f.read()
            if new_py != old_py:
                info(f"Updating lpb.py...")
                with open(new_path, "wb") as f:
                    f.write(new_py)
                new_path.rename(py_path)
        elif not py_path.is_file():
            info(f"Installing missing lpb.py...")
            with open(new_path, "wb") as f:
                f.write(new_py)
            new_path.rename(py_path)
            py_path.chmod(0o755)
        for _f in lpb_dir.iterdir():
            if _f.name.endswith(".new"):
                _f.unlink()
    except Exception as exc:  # network/IO failures should never break startup
        warn(f"self-update skipped: {exc}")

def info(msg):
    """Print an informational message to stdout (no color)."""
    print(msg)


def done(msg):
    """Print a success message (green) to stdout."""
    print(f"\033[32m{msg}\033[0m")


def run_cmd(args: list[str], timeout: int = 120) -> tuple[str, str, int]:
    """Run a subprocess, capture stdout/stderr, and return (stdout, stderr, code)."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", 1
    except FileNotFoundError:
        return "", f"not found: {args[0]}", 127


def ensure_cmd(name: str) -> str | None:
    """Check that a binary exists; return its path or None."""
    return shutil.which(name)


def ensure_container_cmd() -> None:
    """Locate podman or docker; fail with a helpful message if neither exists."""
    if cfg.container_cmd:
        return
    cfg.container_cmd = shutil.which("podman") or shutil.which("docker") or ""
    if not cfg.container_cmd:
        err("podman or docker is required", "Install one of them and retry.")
        raise DevstackError

def is_podman() -> bool:
    """Return True when the container runtime is podman (vs docker)."""
    return "podman" in cfg.container_cmd


def save_last_version(version: str) -> None:
    """Persist the last-used version tag for reconnect/update."""
    _save_version(version)


def load_last_version() -> str:
    """Read the persisted last-used version tag; defaults to empty."""
    return _load_last_version()


def ensure_token() -> str:
    """Return a stable connection token.

    If the user configured one (env/cli), use it unchanged. Otherwise generate a
    random UUID once and persist it under the config dir, so the token lpb prints
    in the URL always matches the token the VSCodium server actually uses.

    If cfg.new_token is set, ignore any persisted token and always generate fresh.
    """
    if cfg.token:
        return cfg.token
    # --new-token flag: always generate fresh, ignore persisted token
    if cfg.new_token:
        fresh = str(uuid.uuid4())
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, "w") as f:
                f.write(fresh)
        except OSError:
            pass
        cfg.token = fresh
        info(f"Generated fresh token: {cfg.token}")
        return fresh
    if TOKEN_FILE.is_file():
        with open(TOKEN_FILE) as f:
            persisted = f.read().strip()
        if persisted:
            cfg.token = persisted
            return persisted
    fresh = str(uuid.uuid4())
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(fresh)
    except OSError:
        pass
    cfg.token = fresh
    return fresh


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

    def containers_exec(self, name: str, command: list[str] | str, tty: bool = True, interactive: bool = True) -> int:
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
        try:
            result = subprocess.run(args, check=False)
            return result.returncode
        except FileNotFoundError:
            print(f"Error: {args[0]} not found", file=sys.stderr)
            return 127

    def pi_running(self, name):
        """Check if a Pi process is running inside the container."""
        args = [self.cmd, "exec", name, "pgrep", "-f", "pi[ck]"]
        _, out, rc = run_cmd(args)
        return rc == 0 and bool(out.strip())

    def containers_logs(self, name: str, follow: bool = True, tail: int | None = None) -> bool:
        args = [self.cmd, "logs"]
        if follow:
            args.append("-f")
        if tail:
            args += ["--tail", str(tail)]
        args.append(name)
        try:
            return subprocess.run(args, check=False).returncode == 0
        except FileNotFoundError:
            print(f"Error: {args[0]} not found", file=sys.stderr)
            return False

    def images_pull(self, name):
        """Pull image with full verbosity, no stdin, and no timeout.
        Uses Popen to stream output in real-time. No stdin to avoid blocking on slow connections."""
        proc = subprocess.Popen(
            [self.cmd, "pull", name],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        import io
        for line in io.TextIOWrapper(proc.stdout.buffer, encoding="utf-8", errors="replace"):
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.stdout.close()
        rc = proc.wait()
        return rc


    def images_inspect(self, name):
        _, _, rc = run_cmd([self.cmd, "image", "inspect", name])
        return rc

    def images_exists(self, name):
        return self.images_inspect(name) == 0

    def version(self):
        _, out, rc = run_cmd([self.cmd, "version", "--format", "{{.Client.Version}}"])
        return out.strip() if rc == 0 else ""


def client():
    """Build a ContainerClient bound to the configured podman/docker runtime."""
    return ContainerClient(cfg.container_cmd)


def resolve_path(p: str) -> str:
    """Expand ~, ${HOME} and make an absolute path."""
    path = Path(p).expanduser()
    if "${HOME}" in str(path):
        path = Path(str(path).replace("${HOME}", HOME))
    return str(path.resolve())


def detect_mount_flags(project_dir: str) -> str:
    """Probe SELinux behaviour and return the appropriate bind-mount flag (:Z/:z)."""
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


def load_config_file() -> None:
    """Load persistent user config (CONFIG_FILE) into the environment, if present."""
    if not CONFIG_FILE.is_file():
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


def load_project_env(project_dir: str) -> None:
    env_file = Path(project_dir) / ".env"
    if not env_file.is_file():
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


def load_project_override(name: str) -> None:
    p = PROJECTS_DIR / name
    if not p.is_file():
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


def apply_overrides(project_dir: str | None = None, project_name: str | None = None, cli_overrides: dict[str, bool] | None = None) -> None:
    load_config_file()
    _apply_env(cli_overrides)
    if project_dir and (Path(project_dir) / ".env").is_file():
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
import argparse

HELP = (
    "lpb \u2014 LocalPibox Devstack launcher\n\n"
    "Usage:\n"
    "  lpb [/path/to/project]           Start Pi CLI session at project\n"
    "  lpb /path -- <pi-args...>        Pass flags through to pi (-p, --session, etc.)\n"
    "  lpb --shell [/path/to/project]   Interactive bash shell in container\n"
    "  lpb --ssh [pubkey|path]          Start sshd server in background (pubkey required)\n"
    "  lpb --web [/path/to/project]     Start VSCodium (background)\n"
    "  lpb --stop                       Stop the container\n"
    "  lpb --remove                     Stop + remove container + state dirs\n"
    "  lpb --logs                       Stream container logs\n"
    "  lpb --update                     Pull latest image(s)\n"
    "  lpb --config                     Show config file location\n"
    "  lpb --help                       Show this help\n\n"
    "Pi passthrough (after \"--\"):\n"
    '  lpb /myproject -- -p "summarize"           # Non-interactive, process & exit\n'
    '  lpb /myproject -- --session abc123          # Resume specific session\n'
    '  lpb /myproject -- --continue                # Continue last session\n'
    '  lpb /myproject -- --mode json -p "analyze"  # JSON mode\n\n'
    "VSCodium options (--web mode only):\n"
    "  --host <HOST>          Host to listen on (default: localhost)\n"
    "  --port <PORT>          Port (default: from .env or 3000)\n"
    "  --token <TOKEN>        Connection token (default: auto-generated)\n"
    "  --new-token            Generate a fresh token (ignore persisted one)\n"
    "  --without-token        Hide token in URL display (server still requires auth)\n\n"
    "Examples:\n"
    "  lpb /path/to/project                    Start Pi CLI at project\n"
    '  lpb /path -- -p "fix the bug"              Non-interactive pi run\n'
    "  lpb --shell /path/to/project            Bash shell in container\n"
    "  lpb --web /path/to/project              Open VSCodium at project\n"
    "  lpb --web --port 8080                   Custom VSCodium port\n"
    "  lpb --without-token                     Hide token in URL display"
)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for all known flags."""
    parser = argparse.ArgumentParser(
        add_help=False,
        description=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--without-token", action="store_true")
    parser.add_argument("--new-token", action="store_true")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--user-data-dir", default=None)
    parser.add_argument("--ext-dir", default=None)
    parser.add_argument("--base-path", default=None)
    parser.add_argument("--ssh-port", type=int, default=None)
    parser.add_argument("--shell", action="store_true")
    parser.add_argument("--ssh", nargs="?", const="", metavar="PUBKEY")
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--tag", default=None,
                        help="Select image pipeline (dev|main|latest|<custom>)")
    parser.add_argument("--version", nargs="?", const="_show",
                        help="Pin to version tag (e.g. 0.0.9-lpb) or show stack version")
    parser.add_argument("--stop", "-s", action="store_true")
    parser.add_argument("--remove", "-r", action="store_true")
    parser.add_argument("--logs", "-l", action="store_true")
    parser.add_argument("--update", "-u", action="store_true")
    parser.add_argument("--config", "-c", action="store_true")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--", dest="_pi_args", nargs=argparse.REMAINDER)
    return parser


def parse_cli(args: list[str]) -> None:
    """Parse CLI args using argparse for known flags; manual handling for -- and positionals."""
    parser = _build_parser()

    # ── Positional command aliases ──────────────────────────────────────
    # Support shorthand: lpb logs / lpb stop / lpb update / lpb remove / lpb config
    # without requiring the -- prefix. Order matters: check commands before paths.
    POSITIONAL_COMMANDS = {"logs": "--logs", "stop": "--stop", "remove": "--remove",
                           "update": "--update", "config": "--config", "help": "--help",
                           "version": "--version"}
    if args and args[0] in POSITIONAL_COMMANDS:
        args[0] = POSITIONAL_COMMANDS[args[0]]

    # Split at -- boundary
    try:
        dash_idx = args.index("--")
        known_args, after_dash = args[:dash_idx], args[dash_idx + 1:]
    except ValueError:
        known_args, after_dash = args, []

    known, extra = parser.parse_known_args(known_args)

    # Apply argparse results to global config
    if known.host is not None:
        cfg.host, _cli_overrides["host"] = known.host, True
    if known.port is not None:
        cfg.port, _cli_overrides["port"] = known.port, True
    if known.token is not None:
        cfg.token, _cli_overrides["token"] = known.token, True
    if known.without_token:
        cfg.without_token = True
    if known.new_token:
        cfg.new_token = True
    if known.data_dir is not None:
        cfg.data_dir = known.data_dir
    if known.user_data_dir is not None:
        cfg.user_data_dir = known.user_data_dir
    if known.ext_dir is not None:
        cfg.ext_dir = known.ext_dir
    if known.base_path is not None:
        cfg.base_path = known.base_path
    if known.ssh_port is not None:
        cfg.ssh_port = str(known.ssh_port)
    if known.shell:
        cfg.shell_mode = True
    if known.web:
        cfg.web_mode = True
    if known.tag is not None:
        cfg.image_tag = known.tag
    if known.version:
        if known.version == "_show" or known.version == "":
            # --version without value → show version and exit
            cfg.command = "version"
        else:
            # --version 0.0.9-lpb → pin to specific version tag
            cfg.image_tag = known.version  # uses :0.0.9-lpb-cli
    if known.stop:
        cfg.command = "stop"
    if known.remove:
        cfg.command = "remove"
    if known.logs:
        cfg.command = "logs"
    if known.update:
        cfg.command = "update"
    if known.config:
        cfg.command = "config"
    if known.help:
        cfg.command = "help"

    # Handle --ssh (special: nargs="?", pubkey may follow)
    if known.ssh is not None:
        cfg.ssh_mode = cfg.shell_mode = True
        if known.ssh:
            p = Path(known.ssh)
            cfg.ssh_pubkey = p.read_text(encoding="utf-8").strip() if p.is_file() else known.ssh.strip()
        if not cfg.ssh_pubkey:
            err("--ssh requires a public key or path to a .pub file",
                "Usage: lpb --ssh 'ssh-ed25519 AAAA... user@host' [/path]")
            raise DevstackError

    # Handle extra/positional args (single-dash flags = error, rest = positional)
    positional: list[str] = []
    for a in extra:
        if a.startswith("-") and not a.startswith("--"):
            err(f"Pi flag '{a}' must come after '--'", "Usage: lpb /path -- -p 'message'")
            raise DevstackError

        positional.append(a)

    # -- passthrough: first non-flag arg after -- is project, rest go to pi
    cfg.pi_args.extend(after_dash)
    if after_dash and not cfg.project_dir and after_dash[0] and not after_dash[0].startswith("-"):
        # First is project dir, rest are pi args
        cfg.project_dir = after_dash[0]
        cfg.pi_args.extend(after_dash[1:])

    # First positional is the project directory
    if positional:
        cfg.project_dir = positional[0]
def cmd_help():
    """Print the full usage/help text and exit."""
    print(HELP); sys.exit(0)


def cmd_stop():
    """Stop and remove the running devstack container (no-op if already stopped)."""
    ensure_container_cmd()
    c = client()
    if not c.container_running(cfg.container_name):
        info(f"Container '{cfg.container_name}' is not running."); sys.exit(0)
    info(f"Stopping {cfg.container_name}...")
    if not c.containers_stop(cfg.container_name):
        err("Failed to stop", "Check: lpb --logs"); raise DevstackError

    c.containers_remove(cfg.container_name)
    done(f"Stopped and removed {cfg.container_name}.")


def cmd_remove():
    """Remove the container plus persisted state/browser data (with confirmation)."""
    ensure_container_cmd()
    c = client()
    c.containers_remove(cfg.container_name)
    dir_browser = Path(resolve_path(cfg.browser_dir))
    for d in (Path(resolve_path(cfg.state_dir)), dir_browser):
        if d.is_dir():
            print(f"\nWarning: this will permanently delete stored data:")
            print(f"  {d}")
            try:
                choice = input("Continue? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "n"
            if choice != "y":
                info("Aborted — nothing was removed.")
                return
            shutil.rmtree(d, ignore_errors=True)
    done("Removed devstack (container, state dir, browser dir).")


def cmd_logs():
    """Stream the devstack container logs (non-following tail)."""
    ensure_container_cmd()
    c = client()
    if not c.container_exists(cfg.container_name):
        err("Container not found", "Run 'lpb' or 'lpb --web' to start a new devstack session.")
        sys.exit(0)
    # Check if container is actually running (not just existed previously)
    if not c.container_running(cfg.container_name):
        err(f"Container '{cfg.container_name}' is stopped", "Start it with: lpb or lpb --web")
        sys.exit(0)
    if not c.containers_logs(cfg.container_name, follow=False):
        err("Failed to get logs", "Try 'lpb --remove' then 'lpb' to start fresh.")
        sys.exit(1)

def cmd_config():
    """Print resolved config, projects, and state paths for the current stack."""
    info(f"Config file: {CONFIG_FILE}")
    info(f"Projects:    {PROJECTS_DIR}")
    info(f"State dir:   {resolve_path(cfg.state_dir)}")


def cmd_version():
    """Show the stack version from the VERSION file and exit."""
    # Search for devstack dir (has both VERSION and lpb.stack.env)
    for candidate in (Path(__file__).parent.parent, Path.cwd()):
        vf = candidate / "VERSION"
        if vf.is_file():
            version = vf.read_text().strip()
            print(f"LocalPibox stack {version}")
            return
        # Check parent dirs
        p = candidate
        for _ in range(10):
            p = p.parent
            vf = p / "VERSION"
            if vf.is_file():
                version = vf.read_text().strip()
                print(f"LocalPibox stack {version}")
                return
            if str(p) == "/":
                break

    # Fallback: read from lpb.stack.env
    stack_env = _find_env_file("lpb.stack.env")
    if stack_env and stack_env.is_file():
        cfg_env = _parse_env_file(stack_env)
        version = cfg_env.get("LPB_PI_REF", "unknown")
        print(f"LocalPibox stack {version}")
        return

    print("unknown")
    sys.exit(0)


def cmd_update():
    """Self-update the launcher and pull the latest devstack image(s)."""
    ensure_container_cmd()
    c = client()

    # Self-update
    self_update()

    # Determine which image(s) to pull
    images_to_update = []
    
    if cfg.image_tag:
        # Resolve versioned image from tag (dev/main/latest/custom)
        cli_img = resolve_cli_image(cfg.image_tag)
        web_img = resolve_web_image(cfg.image_tag)
        # For versioned tags (dev/main), always pull even if not local
        if cfg.image_tag in ("dev", "main"):
            images_to_update = [cli_img, web_img]
        elif c.images_exists(cli_img):
            images_to_update.append(cli_img)
            if c.images_exists(web_img):
                images_to_update.append(web_img)
        else:
            # Custom version not local — fall through to defaults
            pass
    
    if not images_to_update:
        # Fall back to default images
        for img in [CLI_IMAGE, WEB_IMAGE]:
            if c.images_exists(img):
                images_to_update.append(img)

    if not images_to_update:
        err("No devstack images found locally",
            "Run 'lpb' or 'lpb --web' first to pull an image.")
        raise DevstackError

    for img in images_to_update:
        info(f"Pulling {img}...")
        rc = c.images_pull(img)
        if rc != 0:
            err(f"Failed to pull {img}")

    # Save last version for next run
    for img in images_to_update:
        last = img.rsplit(":", 1)[-1]
        if not re.match(r'^0\.0\.\d+-lpb(-dev)?$', last):
            continue
        _save_version(last.replace("-cli", "").replace("-web", ""))
        break

    done("Images up to date.")


def _get_lan_ips():
    """Discover non-loopback IPv4 addresses on the host (used to build connect URLs)."""
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
    """Build the display URL map (host + any LAN/localhost aliases) for web mode."""
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
    """Build a single health-check URL (always localhost-resolved)."""
    check_host = cfg.host
    if check_host in ("0.0.0.0", "localhost", "127.0.0.1"):
        check_host = "127.0.0.1"
    port = cfg.port
    token_part = "" if cfg.without_token else f"?tkn={cfg.token}"
    return f"http://{check_host}:{port}/{token_part}"


def cmd_run():
    """Resolve the project, decide the mode (cli/web/shell/ssh), and launch the
    container. Foreground modes attach interactively; web/ssh run detached.
    Includes recovery prompts when a Pi session is already active."""
    ensure_container_cmd()
    c = client()

    # ── 1. Resolve project directory ─────────────────────────────────────
    project_dir = cfg.project_dir
    if not project_dir:
        if LAST_PROJECT_FILE.is_file():
            with open(LAST_PROJECT_FILE) as f:
                project_dir = f.read().strip()
    if not project_dir:
        cfg.open_home = True
        project_dir = HOME
    project_dir = resolve_path(project_dir)
    if not Path(project_dir).is_dir():
        hint = (
            f"Make sure the path is correct and exists: {project_dir}\n"
            "  Create it:  mkdir -p {project_dir}\n"
            "  List projects:  lpb --config"
        )
        err(f"directory not found: {project_dir}", hint)
        raise DevstackError

    # ── 2. Project name ──────────────────────────────────────────────────
    cfg.project_name = Path(project_dir).name
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$', cfg.project_name):
        err(f"project name '{cfg.project_name}' contains invalid characters",
            "Use only alphanumeric, dots, hyphens, underscores.")
        raise DevstackError

    # ── 3. Mount path inside container ───────────────────────────────────
    if cfg.open_home:
        mount_path = "/home/lpb/workspace"
    else:
        mount_path = f"/home/lpb/workspace/{cfg.project_name}"

    # ── 4. Determine image and mode ──────────────────────────────────────
    tag = cfg.image_tag
    if cfg.web_mode:
        cfg.image_name = resolve_web_image(tag)
        mode_label = "web (VSCodium)"
    elif cfg.shell_mode:
        cfg.image_name = resolve_cli_image(tag)
        mode_label = "cli (ssh server)" if cfg.ssh_pubkey else "cli (shell)"
    else:
        cfg.image_name = resolve_cli_image(tag)
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

    # ── 7. Shell mode: attach to existing container ─────────────────────
    # (SSH mode skips this — it always does a fresh detached server)
    if cfg.shell_mode and not cfg.ssh_mode:
        if c.container_running(cfg.container_name):
            pi_active = c.pi_running(cfg.container_name)
            if pi_active:
                info(f"Container '{cfg.container_name}' running (Pi session active).")
                info("\nOptions:")
                print("  1) Attach to Pi session  (foreground)")
                print("  2) Open bash shell      (interactive shell)")
                print("  3) Stop container and restart")
                try:
                    choice = input("\nSelect [1-3] (default: 1): ").strip() or "1"
                except (EOFError, KeyboardInterrupt):
                    choice = "1"
                if choice == "2":
                    info(f"Opening bash shell in '{cfg.container_name}'...")
                    ret = c.containers_exec(cfg.container_name, ["bash"], tty=True, interactive=True)
                    sys.exit(ret)
                elif choice == "3":
                    info(f"Stopping '{cfg.container_name}'...")
                    c.containers_stop(cfg.container_name)
                else:
                    # Reconnect to Pi session via exec
                    info(f"Reconnecting to Pi session in '{cfg.container_name}'...")
                    ret = c.containers_exec(
                        cfg.container_name,
                        ["pi", "--continue"],
                        tty=True, interactive=True
                    )
                    sys.exit(ret)
            else:
                info(f"Attaching to running container '{cfg.container_name}'...")
                ret = c.containers_exec(cfg.container_name, ["bash"], tty=True, interactive=True)
                sys.exit(ret)
        elif c.container_exists(cfg.container_name):
            info(f"Container '{cfg.container_name}' is stopped — starting it...")
            _, _, rc = run_cmd([cfg.container_cmd, "start", cfg.container_name])
            if rc != 0:
                err("Failed to start container", "Try 'lpb --remove' then 'lpb --shell'.")
                raise DevstackError

            info(f"Attaching to container '{cfg.container_name}'...")
            ret = c.containers_exec(cfg.container_name, ["bash"], tty=True, interactive=True)
            sys.exit(ret)
        else:
            info("No running container — starting a fresh devstack session...")
            # fall through to full startup flow (steps 8+)

    # ── 8. Check for running Pi session ──────────────────────────────────
    if cfg.web_mode or cfg.ssh_mode:
        # Web/SSH mode: stop existing container (server must restart)
        if c.container_running(cfg.container_name):
            info("Stopping existing devstack container...")
            c.containers_stop(cfg.container_name)
    else:
        # CLI mode: check if Pi is running
        if c.container_running(cfg.container_name) and c.pi_running(cfg.container_name):
            # Pi session active — offer recovery
            info(f"Pi session active in running container '{cfg.container_name}'.")
            info("")
            print("  1) Reconnect to session (continue)")
            print("  2) Stop container and start fresh")
            try:
                choice = input("\nSelect [1-2] (default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                choice = "1"

            if choice == "2":
                info(f"Stopping '{cfg.container_name}'...")
                c.containers_stop(cfg.container_name)
            else:
                # Reconnect to existing session
                info(f"Connecting to existing Pi session in '{cfg.container_name}'...")
                ret = c.containers_exec(
                    cfg.container_name,
                    ["pi", "--continue"],
                    tty=True, interactive=True
                )
                sys.exit(ret)

    # ── 9. Pull image if needed ──────────────────────────────────────────
    if not c.images_exists(cfg.image_name):
        info(f"Pulling {cfg.image_name}...")
        rc = c.images_pull(cfg.image_name)
        if rc != 0:
            err("Failed to pull image")
            raise DevstackError

    # ── 10. Detect SELinux mount flags ────────────────────────────────────
    mount_flags = detect_mount_flags(project_dir)

    # ── 11. Remove stale stopped containers ───────────────────────────────
    if c.container_exists(cfg.container_name):
        info(f"Removing stale container '{cfg.container_name}'...")
        c.containers_remove(cfg.container_name)

    # ── 12. Build env vars and volumes ───────────────────────────────────
    # Resolve a stable connection token (generate+persist if unset) so the URL
    # lpb prints matches the token the VSCodium server actually enforces.
    ensure_token()
    
    env_vars = [
        f"LPB_ED_PORT={cfg.port}",
        f"LPB_EDITOR_HOST={cfg.host}",
        f"LPB_DEVCONTAINER_WORKSPACE_DIR={mount_path}",
        f"LPB_CONNECTION_TOKEN={cfg.token}",
        f"CONNECTION_TOKEN={cfg.token}",
        # NOTE: LPB_PI_REF and LPB_CONFIG_REF are NOT passed as env vars.
        # The image is built with these baked in (LPB_PI_REF is the version
        # tag or branch ref). The image IS the configuration reference —
        # lpb.py just selects which pre-built image to use.
        # Note: LPB_STATE_DIR is NOT passed to the container. It's a launcher-time
        # config (lpb.py reads it to resolve the host mount source). The container
        # has no need for it — start.sh uses its own defaults. Passing it here
        # would pollute .devstack-env and break future host runs.
        f"LPB_EXA_API_KEY={os.environ.get('LPB_EXA_API_KEY', os.environ.get('EXA_API_KEY', ''))}",
        f"LPB_MAX_TOKENS_CONTEXT_RATIO={os.environ.get('LPB_MAX_TOKENS_CONTEXT_RATIO', _conf_cfg.get('LPB_MAX_TOKENS_CONTEXT_RATIO', '0.06'))}",
    ]
    for k in ("PI_WORKTREE_ID", "LPB_AGENT_BROWSER_ARGS", "LPB_AGENT_BROWSER_MAX_OUTPUT",
              "LPB_AGENT_BROWSER_CONTENT_BOUNDARIES", "LPB_AGENT_BROWSER_CONFIRM_ACTIONS",
              "LPB_AGENT_BROWSER_IDLE_TIMEOUT_MS", "LPB_AGENT_BROWSER_SESSION"):
        val = os.environ.get(k)
        if val:
            env_vars.append(f"{k}={val}")
        elif k in _conf_cfg:
            env_vars.append(f"{k}={_conf_cfg[k]}")

    # ── 12b. Shell / SSH start mode ─────────────────────────────────────
    # When starting a container for --shell/--ssh (no existing container),
    # override the CLI entrypoint to the shell sshd mode so we get a bare
    # shell (or sshd) instead of a Pi session.
    if cfg.shell_mode:
        env_vars.append("LPB_START_MODE=shell")
        if cfg.ssh_pubkey:
            env_vars.append(f"LPB_SSH_PUBKEY={cfg.ssh_pubkey}")
            env_vars.append(f"LPB_SSH_PORT={cfg.ssh_port}")

    volumes = [
        f"{project_dir}:{mount_path}{mount_flags}",
        f"{resolved_state}:/home/lpb/.pi{mount_flags}",
        f"{dir_browser}:/home/lpb/.agent-browser{mount_flags}",
    ]
    # ── 13. Mount gh config (persisted across restarts) ──────────────────
    gh_config = resolve_path(str(Path(cfg.state_dir) / "gh-config"))
    Path(gh_config).mkdir(parents=True, exist_ok=True)
    volumes.append(f"{gh_config}:/home/lpb/.config/gh{mount_flags}")
    # ── 13b. Sync timezone with host (read-only; no relabel needed) ──────
    # Bind-mount the host's /etc/localtime (and /etc/timezone if present) so
    # the container time always matches the host. Read-only, no Z/z relabel.
    if Path("/etc/localtime").is_file():
        volumes.append("/etc/localtime:/etc/localtime:ro")
    if Path("/etc/timezone").is_file():
        volumes.append("/etc/timezone:/etc/timezone:ro")

    userns = "keep-id" if is_podman() else None

    # ── 13. Run container ────────────────────────────────────────────────
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
            raise DevstackError

        LAST_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LAST_PROJECT_FILE, "w") as f:
            f.write(project_dir)
        # Save version from image name (e.g. :0.0.9-lpb-dev-web → 0.0.9-lpb-dev)
        _save_version(cfg.image_name.split(":")[-1].replace("-web", ""))

        # Health check — retry with increasing tolerance.
        # VSCodium server needs time to bind, load extensions, and serve.
        # Three-tier approach: TCP connect → HTTP root → /api/version.
        health_url = _build_url()
        # Build base URL without token for version check
        check_host = cfg.host
        if check_host in ("0.0.0.0", "localhost", "127.0.0.1"):
            check_host = "127.0.0.1"
        base_url = f"http://{check_host}:{cfg.port}"
        ready = False
        tcp_ok = False
        try:
            for i in range(120):
                # TCP connect check (always try, lightweight)
                if not tcp_ok:
                    try:
                        s = socket.create_connection((check_host, cfg.port), timeout=2)
                        s.close()
                        tcp_ok = True
                    except (socket.timeout, socket.error, OSError):
                        pass

                # Phase 1 (0-15s): HTTP root check (fast)
                if i < 15 and tcp_ok:
                    try:
                        r = subprocess.run(
                            ["curl", "-s", "--max-time", "2",
                             "--connect-timeout", "2",
                             health_url],
                            capture_output=True, timeout=4
                        )
                        if r.returncode == 0:
                            ready = True; break
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        pass

                # Phase 2 (15-45s): HTTP root with longer timeout
                elif i < 45 and tcp_ok:
                    try:
                        r = subprocess.run(
                            ["curl", "-s", "--max-time", "5",
                             "--connect-timeout", "3",
                             health_url],
                            capture_output=True, timeout=8
                        )
                        if r.returncode == 0:
                            ready = True; break
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        pass

                # Phase 3 (45-75s): /api/version endpoint (bypasses auth)
                elif i < 75 and tcp_ok:
                    try:
                        r = subprocess.run(
                            ["curl", "-s", "--max-time", "5",
                             "--connect-timeout", "3",
                             f"{base_url}/api/version"],
                            capture_output=True, timeout=8
                        )
                        if r.returncode == 0 and r.stdout.strip():
                            ready = True; break
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        pass

                # Phase 4 (75-120s): try HTTP root without token
                elif i < 120 and tcp_ok:
                    try:
                        r = subprocess.run(
                            ["curl", "-s", "--max-time", "5",
                             "--connect-timeout", "3",
                             base_url],
                            capture_output=True, timeout=8
                        )
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
    elif cfg.ssh_mode:
        # SSH mode: background sshd server — user logs in remotely
        info("Starting SSH server (background)...")
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
            raise DevstackError

        LAST_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LAST_PROJECT_FILE, "w") as f:
            f.write(project_dir)
        # Save version from image name
        _save_version(cfg.image_name.split(":")[-1].replace("-cli", ""))

        host = _get_host_for_url()
        port = cfg.ssh_port
        user = "lpb"  # container user (uid 1000) is lpb
        done("\u2713 SSH server ready (background)")
        info(f"  Connect:  ssh -p {port} {user}@{host}")
        info(f"  Pubkey:   {cfg.ssh_pubkey}")
        info("")
        info("  The container runs in the background with the provided public\n"
              "  key in authorized_keys. Your private key is never uploaded.\n"
              "  Manage it with:")
        info("    lpb --stop      \u2014 Stop the SSH server")
        info("    lpb --logs      \u2014 View logs")
    else:
        # CLI mode: foreground, stop on exit
        info("Starting container (foreground)...\n")
        # Save last-project for reconnection
        LAST_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LAST_PROJECT_FILE, "w") as f:
            f.write(project_dir)
        # Save version from image name
        _save_version(cfg.image_name.split(":")[-1].replace("-cli", ""))
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
        if cfg.pi_args:
            args += cfg.pi_args
        ret = subprocess.run(args, check=False).returncode
        # Container is removed (--rm), nothing to clean up


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point: parse args, dispatch to the selected command handler."""
    parse_cli(sys.argv[1:])
    apply_overrides(cfg.project_dir, cfg.project_name, _cli_overrides)

    handlers = {
        "help": cmd_help,
        "version": cmd_version,
        "stop": cmd_stop,
        "remove": cmd_remove,
        "logs": cmd_logs,
        "update": cmd_update,
        "config": cmd_config,
        "run": cmd_run,
    }
    handlers.get(cfg.command, cmd_run)()


if __name__ == "__main__":
    main()
