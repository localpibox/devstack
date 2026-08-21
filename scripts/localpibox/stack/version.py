"""Pipeline detection, VERSION discovery and bump math, stack env loading.

The VERSION file is the single source of the stack version (manual tagging —
CI never writes it). These helpers find it, parse/bump it, and derive the
dev-vs-main pipeline.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..env import parse_env_file
from .repos import (
    _DEVSTACK_ROOT,
    VERSION_RE,
    WORKSPACE_REPOS,
    WORKSPACE_ROOT,
)


# ─── Pipeline detection ───────────────────────────────────────────────────

def detect_pipeline(tag_override: str | None = None) -> str:
    """Detect the current pipeline (dev or main).

    Priority:
      1. tag_override (--tag argument)
      2. LPB_IMAGE_TAG env var
      3. VERSION file content (contains '-lpb-dev' → dev, else main)
      4. LPB_VERSION env var (contains '-dev' → dev, else main)
      5. default: dev
    """
    if tag_override and tag_override != "_show":
        return "dev" if tag_override in ("dev",) else "main"

    env_tag = os.environ.get("LPB_IMAGE_TAG", "")
    if env_tag:
        return "dev" if env_tag == "dev" else "main"

    # Read VERSION file
    vf = _find_version_file()
    if vf is not None:
        version = vf.read_text().strip()
        if "-dev" in version:
            return "dev"
        return "main"

    # LPB_VERSION env var (baked in image)
    lpb_version = os.environ.get("LPB_VERSION", "")
    if lpb_version:
        return "dev" if "-dev" in lpb_version else "main"

    return "dev"  # default


# ─── VERSION discovery ─────────────────────────────────────────────────────

def get_version() -> str:
    """Read the current stack VERSION."""
    vf = _find_version_file()
    if vf is not None:
        return vf.read_text().strip()
    return os.environ.get("LPB_VERSION", "unknown")


_VERSION_FILE: Path | None = None  # cache

def _find_version_file() -> Path | None:
    """Find the VERSION file (cached)."""
    global _VERSION_FILE
    if _VERSION_FILE is not None:
        return _VERSION_FILE
    for candidate in (
        _DEVSTACK_ROOT / "VERSION",
        Path("/opt/devstack/VERSION"),
        WORKSPACE_ROOT / "devstack" / "VERSION",
    ):
        if candidate.is_file():
            _VERSION_FILE = candidate
            return candidate
    return None


# ─── Stack env ─────────────────────────────────────────────────────────────

def get_stack_env(pipeline: str) -> dict[str, str]:
    """Load the stack env for the given pipeline.

    Returns LPB_PI_REF, LPB_CONFIG_REF, etc.
    """
    base_env: dict[str, str] = {}
    for candidate in (
        _DEVSTACK_ROOT / "lpb.stack.env",
        Path("/opt/devstack/lpb.stack.env"),
        WORKSPACE_ROOT / "devstack" / "lpb.stack.env",
    ):
        if candidate.is_file():
            base_env = parse_env_file(candidate)
            break

    # Overlay pipeline-specific env
    for candidate in (
        _DEVSTACK_ROOT / f"lpb.stack.{pipeline}.env",
        Path("/opt/devstack") / f"lpb.stack.{pipeline}.env",
        WORKSPACE_ROOT / "devstack" / f"lpb.stack.{pipeline}.env",
    ):
        if candidate.is_file():
            base_env.update(parse_env_file(candidate))
            break

    return base_env


def expected_branch(repo_name: str, pipeline: str) -> str:
    """Return the expected branch for a repo given the pipeline."""
    for name, _, _, dev_branch, main_branch in WORKSPACE_REPOS:
        if name == repo_name:
            return dev_branch if pipeline == "dev" else main_branch
    return ""


# ─── VERSION bumping (pure logic) ─────────────────────────────────────────

def parse_version(version: str) -> tuple[int, int, int, str] | None:
    """Parse a stack version string → ``(major, minor, patch, suffix)``.

    ``suffix`` is ``-lpb`` or ``-lpb-dev``. Returns None when invalid.
    """
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(-lpb(-dev)?)", version.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4))


def bump_version(version: str, kind: str = "patch") -> str:
    """Bump a stack version (patch/minor/major), preserving the -lpb[-dev] suffix."""
    parsed = parse_version(version)
    if parsed is None:
        raise ValueError(
            f"invalid version format: {version!r} (expected 0.x.y-lpb[-dev])")
    major, minor, patch, suffix = parsed
    if kind == "patch":
        patch += 1
    elif kind == "minor":
        minor += 1
        patch = 0
    elif kind == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"unknown bump kind: {kind!r} (patch|minor|major)")
    return f"{major}.{minor}.{patch}{suffix}"
