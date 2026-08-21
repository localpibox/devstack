"""LocalPibox stack constants and repository definitions.

Single source of truth for the workspace layout, the 6-repo stack map,
and the release-tagging repo list. Also the one-time legacy ~/.pi layout
migration.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from ..log import Console

# ─── Path constants ─────────────────────────────────────────────────────────

# Devstack repo root (this file lives in <devstack>/scripts/localpibox/stack/).
# In the Docker image this resolves to /opt — harmless, the version-file
# candidates fall through to /opt/devstack and the workspace.
_DEVSTACK_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_AGENT_DIR = os.environ.get("AGENT_DIR", "/home/lpb/.pi/agent")
DEFAULT_REMOTE = os.environ.get("CONFIG_REMOTE", "https://github.com/lpb-stack/config.git")
DEFAULT_REF = os.environ.get("CONFIG_REF", "main")

WORKSPACE_ROOT = Path(os.environ.get("LPB_WORKSPACE_ROOT", "/home/lpb/workspace"))
AGENT_GIT = Path(os.environ.get(
    "LPB_AGENT_GIT", f"{DEFAULT_AGENT_DIR}/git/github.com/lpb-stack"))

MIGRATE_KEEP = {".initialized", "ssh-host-keys", "gh-config", "agent"}

# Canonical stack VERSION format (0.x.y-lpb[-dev]) — must match the
# devstack pre-commit hook.
VERSION_RE = re.compile(r"^0\.[0-9]+\.[0-9]+-lpb(-dev)?$")

# ─── Workspace repo definitions ───────────────────────────────────────────
# Each repo: (name, is_symlink, is_extension, dev_branch, main_branch)
#   is_symlink: workspace repo is a symlink → .pi/agent/git/...
#   is_extension: repo is installed as a Pi extension
#   dev_branch / main_branch: expected branch for each pipeline

WORKSPACE_REPOS = [
    # (name, is_symlink, is_extension, dev_branch, main_branch)
    ("devstack",          False, False, "dev",    "main"),
    ("lemonade-pi-plugin", True,  True,  "lpb-dev", "lpb"),
    ("lpb-memory",        True,  True,  "dev",    "main"),
    ("pi-subagents",      True,  True,  "lpb-dev", "lpb"),
    ("pi",                False, False, "lpb-dev", "lpb"),
]

EXTENSION_REPOS = [r for r in WORKSPACE_REPOS if r[2]]  # is_extension

# Repos tagged per release — the 5 stack repos excluding devstack (devstack
# is tracked by its VERSION file, never tagged). Mirrors the CI tag-repos job.
TAG_REPOS = [
    # (name, dev_branch, main_branch)
    ("pi", "lpb-dev", "lpb"),
    ("pi-subagents", "lpb-dev", "lpb"),
    ("lemonade-pi-plugin", "lpb-dev", "lpb"),
    ("config", "dev", "main"),
    ("lpb-memory", "dev", "main"),
]

LPB_EXTENSION_REPOS = ["lemonade-pi-plugin", "lpb-memory", "pi-subagents"]

MEMORY_CONFIG_PATH = Path(DEFAULT_AGENT_DIR) / "lpb-memory-config.json"
MEMORY_CONFIG_TEMPLATE = Path(DEFAULT_AGENT_DIR) / "lpb-memory-config.json.template"


def _repo_remote(name: str) -> str:
    """GitHub remote URL for a stack repo (LPB_STACK_REMOTE_BASE override for tests/offline)."""
    base = os.environ.get("LPB_STACK_REMOTE_BASE", "https://github.com/lpb-stack").rstrip("/")
    return f"{base}/{name}.git"


def migrate_legacy_layout(pi_root: str | Path, agent_dir: str | Path, cons: Console) -> None:
    """Move legacy ``~/.pi`` root layout contents into ``~/.pi/agent/`` (one-time)."""
    pi_root, agent_dir = Path(pi_root), Path(agent_dir)
    if (pi_root / ".git").is_dir() and not (agent_dir / ".git").is_dir():
        cons.info(f"Migrating legacy config layout from {pi_root} to {agent_dir} ...")
        agent_dir.mkdir(parents=True, exist_ok=True)
        for item in pi_root.iterdir():
            if item.name in MIGRATE_KEEP:
                continue
            try:
                shutil.move(str(item), str(agent_dir / item.name))
            except OSError:
                pass
        cons.info(f"Legacy config layout migrated to {agent_dir}.")
