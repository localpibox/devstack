"""Git helpers for LocalPibox stack tools.

Plain and GitHub-auth-aware git invocations, repo-scoped and remote-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..run import run_cmd


def _github_token() -> str:
    """Return GitHub token from environment."""
    return os.environ.get("LPB_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _git_authenticated(args: list[str]) -> list[str]:
    """Prepend auth-aware git URL override when token is available."""
    token = _github_token()
    if token:
        return [
            "git",
            "-c", f"url.\"https://x-access-token:{token}@github.com/\".insteadOf=\"https://github.com/\"",
        ] + args
    return ["git"] + args


def git(dir_: str | Path, *args: str, timeout: int = 120) -> tuple[str, str, int]:
    """Run a git command scoped to *dir_*; returns ``(out, err, code)``."""
    cmd = ["git", "-C", str(dir_), *args]
    return run_cmd(cmd, timeout=timeout)


def git_auth(dir_: str | Path, *args: str, timeout: int = 120) -> tuple[str, str, int]:
    """Run a git command with GitHub auth (when token available), scoped to *dir_*.

    Uses ``-c url.insteadOf`` to inject the token for https://github.com/ URLs.
    """
    cmd = _git_authenticated(["-C", str(dir_), *args])
    return run_cmd(cmd, timeout=timeout)


def git_remote(*args: str, timeout: int = 120) -> tuple[str, str, int]:
    """Run a git command not scoped to a local repo (ls-remote, push <url> ...)."""
    return run_cmd(_git_authenticated(list(args)), timeout=timeout)
