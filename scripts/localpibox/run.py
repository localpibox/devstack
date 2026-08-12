"""Subprocess and environment helpers shared by LocalPibox tools.

Promotes `run_cmd`/`is_podman`-style helpers from `scripts/lpb.py` and the
tool-discovery logic scattered across the shell scripts into one place.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Callable

Runner = Callable[[list[str]], tuple[str, str, int]]


def run_cmd(
    args: list[str],
    *,
    timeout: int = 120,
    input_text: str | None = None,
    cwd: str | None = None,
) -> tuple[str, str, int]:
    """Run a subprocess and return ``(stdout, stderr, returncode)``.

    Never raises for a non-zero exit; ``check=False`` semantics. Maps
    ``TimeoutExpired`` to ``("", "timed out after Ns", 1)`` and a missing
    binary to ``("", "not found: <name>", 127)``.
    """
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", f"timed out after {timeout}s", 1
    except FileNotFoundError:
        return "", f"not found: {args[0]}", 127


def which(*names: str) -> str | None:
    """Return the path of the first *name* found on PATH, else ``None``."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def require(*names: str, what: str = "tool(s)") -> None:
    """Raise ``RuntimeError`` if any of *names* is not on PATH."""
    missing = [n for n in names if not shutil.which(n)]
    if missing:
        raise RuntimeError(f"missing required {what}: {', '.join(missing)}")


def is_container() -> bool:
    """Return True when running inside a container (docker/podman).

    Mirrors the detection in ``install-browser.sh``: marker files, the
    ``/proc/1/cgroup`` contents, and systemd-detect-virt (best effort).
    """
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8", errors="replace") as f:
            contents = f.read()
        if "docker" in contents or "podman" in contents:
            return True
    except OSError:
        pass
    try:
        if shutil.which("systemd-detect-virt"):
            out, _, code = run_cmd(["systemd-detect-virt", "-q"], timeout=10)
            if code == 0:
                return True
    except Exception:
        pass
    return False


def print_env(name: str) -> str:
    """Return the value of env var *name* ('' when unset)."""
    return os.environ.get(name, "")


__all__ = ["Runner", "is_container", "print_env", "require", "run_cmd", "which"]
