#!/usr/bin/env python3
"""lpb-config — Manage the LocalPibox stack config, workspace, and validation.

Usage:
  lpb-config status    — Show config repo commit, remote HEAD, local changes
  lpb-config update    — Fetch + fast-forward config repo (safe: refuses on local changes)
  lpb-config reset     — Re-clone config repo, destroy local changes (with confirmation)
  lpb-config merge     — Open git merge flow for advanced users
  lpb-config align     — Align settings.json extension pins to latest tags

  lpb-config workspace status   — Show workspace repo branches + alignment
  lpb-config workspace sync     — Create symlinks + git pull current branches
  lpb-config workspace ensure   — Switch repos to correct branches for pipeline

  lpb-config validate           — Validate entire stack alignment to current pipeline

Pipeline detection:
  Reads VERSION file to determine pipeline (dev vs main). Override with --tag.

Environment:
  AGENT_DIR         — Config repo path (default: /home/lpb/.pi/agent)
  CONFIG_REMOTE     — Git remote URL (default: https://github.com/lpb-stack/config.git)
  CONFIG_REF        — Branch to track (default: main)
  LPB_GITHUB_TOKEN  — GitHub token for authenticated operations
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

_SELF_DIR = Path(__file__).resolve().parent
for _c in (_SELF_DIR.parent / "scripts", _SELF_DIR, Path("/opt/pi-support")):
    if (_c / "lpb-stack").is_dir():
        sys.path.insert(0, str(_c))
        break

from lpb-stack.cli import confirm, install_sigpipe_handler  # noqa: E402
from lpb-stack.env import parse_env_file  # noqa: E402
from lpb-stack.log import Console  # noqa: E402
from lpb-stack.run import run_cmd  # noqa: E402

# ─── Constants ──────────────────────────────────────────────────────────────

DEFAULT_AGENT_DIR = "/home/lpb/.pi/agent"
DEFAULT_REMOTE = "https://github.com/lpb-stack/config.git"
DEFAULT_REF = "main"

WORKSPACE_ROOT = Path("/home/lpb/workspace")
AGENT_GIT = Path("/home/lpb/.pi/agent/git/github.com/lpb-stack")

MIGRATE_KEEP = {".initialized", "ssh-host-keys", "gh-config", "agent"}

# ─── Workspace repo definitions ───────────────────────────────────────────
# Each repo: (name, is_symlink, is_extension, dev_branch, main_branch, fork_remote)
#   is_symlink: workspace repo is a symlink → .pi/agent/git/...
#   is_extension: repo is installed as a Pi extension
#   dev_branch / main_branch: expected branch for each pipeline
#   fork_remote: GitHub fork URL (for cloning)

WORKSPACE_REPOS = [
    # (name, is_symlink, is_extension, dev_branch, main_branch)
    ("devstack",          False, False, "dev",    "main"),
    ("lemonade-pi-plugin", True,  True,  "lpb-dev", "lpb"),
    ("lpb-memory",        True,  True,  "dev",    "main"),
    ("pi-subagents",      True,  True,  "lpb-dev", "lpb"),
    ("pi",                False, False, "lpb-dev", "lpb"),
]

EXTENSION_REPOS = [r for r in WORKSPACE_REPOS if r[2]]  # is_extension


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


def get_version() -> str:
    """Read the current stack VERSION."""
    for candidate in (
        _SELF_DIR.parent / "VERSION",
        Path("/opt/devstack/VERSION"),
        WORKSPACE_ROOT / "devstack" / "VERSION",
    ):
        if candidate.is_file():
            return candidate.read_text().strip()
    return os.environ.get("LPB_VERSION", "unknown")


_VERSION_FILE: Path | None = None  # cache

def _find_version_file() -> Path | None:
    """Find the VERSION file (cached)."""
    global _VERSION_FILE
    if _VERSION_FILE is not None:
        return _VERSION_FILE
    for candidate in (
        _SELF_DIR.parent / "VERSION",
        Path("/opt/devstack/VERSION"),
        WORKSPACE_ROOT / "devstack" / "VERSION",
    ):
        if candidate.is_file():
            _VERSION_FILE = candidate
            return candidate
    return None


def get_stack_env(pipeline: str) -> dict[str, str]:
    """Load the stack env for the given pipeline.

    Returns LPB_PI_REF, LPB_CONFIG_REF, etc.
    """
    # Load base lpb.stack.env
    base_env = {}
    for candidate in (
        _SELF_DIR.parent / "lpb.stack.env",
        Path("/opt/devstack/lpb.stack.env"),
        WORKSPACE_ROOT / "devstack" / "lpb.stack.env",
    ):
        if candidate.is_file():
            base_env = parse_env_file(candidate)
            break

    # Overlay pipeline-specific env
    for candidate in (
        _SELF_DIR.parent / f"lpb.stack.{pipeline}.env",
        Path("/opt/devstack/lpb.stack.") / f"{pipeline}.env",
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


# ─── Legacy layout migration ──────────────────────────────────────────────

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


# ─── Config repo commands ─────────────────────────────────────────────────

def clone_or_init(agent_dir: str | Path, remote: str, ref: str, cons: Console) -> bool:
    """Clone the config repo, or initialize it in place when the target is
    non-empty (stale runtime state). Mirrors the logic in start.sh."""
    agent_dir = Path(agent_dir)
    if agent_dir.is_dir() and any(agent_dir.iterdir()):
        cons.warn("Config area not empty — initializing config repo in place...")
        git(agent_dir, "init", "-q")
        git(agent_dir, "remote", "add", "origin", remote)
        out, err, code = git(agent_dir, "fetch", "--depth=1", "origin", ref)
        if code:
            cons.error(f"Failed to fetch config repo: {err.strip() or out.strip()}")
            return False
        git(agent_dir, "reset", "-q", "--hard", f"origin/{ref}")
        return True
    out, err, code = run_cmd(
        ["git", "clone", "--depth=1", "--branch", ref, remote, str(agent_dir)],
        timeout=300,
    )
    if code:
        cons.error(f"Failed to clone config repo: {err.strip() or out.strip()}")
        return False
    return True


def head_short(dir_: str | Path) -> str:
    out, _, _ = git(dir_, "rev-parse", "HEAD")
    return out.strip()[:8] or "?"


def cmd_status(agent_dir: str | Path, remote: str, ref: str, cons: Console) -> int:
    if not (Path(agent_dir) / ".git").is_dir():
        cons.warn(f"No config repo at {agent_dir}")
        cons.info("  Run 'lpb-config update' to clone it.")
        return 0

    cur = head_short(agent_dir)
    log = git(agent_dir, "log", "--oneline", "-1")[0].strip() or "?"
    cons.info(f"Current:     {cur} ({log})")

    out, _, code = git(agent_dir, "remote", "get-url", "origin")
    if code or not out.strip():
        cons.warn("No remote configured")
        return 0

    remote_head = git(agent_dir, "rev-parse", f"origin/{ref}")[0].strip()
    if remote_head:
        cons.info(f"Remote:      {remote_head[:8]} origin/{ref}")

    changes = git(agent_dir, "status", "--porcelain")[0]
    if changes.strip():
        cons.warn(f"Uncommitted changes detected ({len(changes.splitlines())} lines):")
        for line in changes.splitlines()[:10]:
            cons.raw(line)
    else:
        cons.info("Working tree: clean")

    if remote_head:
        _, _, code = git(agent_dir, "merge-base", "--is-ancestor", cur, remote_head)
        if code == 0:
            cons.info("Status:      up to date (or ahead)")
        else:
            cons.warn("Status:      behind remote — run 'lpb-config update' to fetch")
    return 0


def cmd_update(agent_dir: str | Path, remote: str, ref: str, cons: Console) -> int:
    if not (Path(agent_dir) / ".git").is_dir():
        cons.info(f"Cloning config repo from {remote}...")
        if not clone_or_init(agent_dir, remote, ref, cons):
            return 1
        cons.info("Done. Run 'lpb-config status' to verify.")
        return 0

    cons.info(f"Fetching updates from {remote}...")
    out, err, code = git(agent_dir, "fetch", "origin", ref)
    if code:
        cons.error(f"Failed to fetch from {remote}: {err.strip() or out.strip()}")
        return 1

    remote_head = git(agent_dir, "rev-parse", f"origin/{ref}")[0].strip()
    cur_head = git(agent_dir, "rev-parse", "HEAD")[0].strip()
    if remote_head == cur_head:
        cons.info("Already up to date.")
        return 0

    changes = git(agent_dir, "status", "--porcelain")[0]
    if changes.strip():
        cons.warn("Uncommitted changes detected:")
        cons.raw(changes)
        cons.warn("Aborting — local changes would be lost.")
        cons.info("")
        cons.info("Options:")
        cons.info("  1. Commit your changes first, then re-run 'lpb-config update'")
        cons.info("  2. Use 'lpb-config reset' to discard local changes (destructive)")
        cons.info("  3. Use 'lpb-config merge' for an interactive git merge")
        return 1

    _, _, code = git(agent_dir, "merge-base", "--is-ancestor", cur_head, remote_head)
    if code == 0:
        git(agent_dir, "reset", "--hard", f"origin/{ref}")
        log = git(agent_dir, "log", "--oneline", "-1")[0].strip()
        cons.info(f"Updated to {log}")
        return 0

    cons.warn("Cannot fast-forward — conflicts detected.")
    cons.info("")
    cons.info("Run 'lpb-config merge' for an interactive merge, or")
    cons.info("use 'lpb-config reset' to discard local changes (destructive).")
    return 1


def cmd_reset(
    agent_dir: str | Path,
    remote: str,
    ref: str,
    cons: Console,
    *,
    force: bool = False,
    inp=None,
) -> int:
    if not (Path(agent_dir) / ".git").is_dir():
        cons.info(f"Cloning config repo from {remote}...")
        if not clone_or_init(agent_dir, remote, ref, cons):
            return 1
        cons.info("Done.")
        return 0

    cons.warn(f"This will destroy ALL local changes in {agent_dir}.")
    cons.raw(f"  Current: {head_short(agent_dir)}")
    remote_head = git(agent_dir, "rev-parse", f"origin/{ref}")[0].strip()[:8]
    cons.raw(f"  Remote:  {remote_head}")

    if not force and not confirm("  Continue?", default=False, inp=inp):
        cons.info("Aborted.")
        return 0

    shutil.rmtree(agent_dir, ignore_errors=True)
    if not clone_or_init(agent_dir, remote, ref, cons):
        return 1
    cons.info("Reset complete. Re-run Pi to apply the new config.")
    return 0


def cmd_merge(agent_dir: str | Path, remote: str, ref: str, cons: Console) -> int:
    if not (Path(agent_dir) / ".git").is_dir():
        cons.error(f"No config repo at {agent_dir}. Run 'lpb-config update' first.")
        return 1

    cons.info(f"Fetching latest from {remote}...")
    git(agent_dir, "fetch", "origin", ref)

    remote_head = git(agent_dir, "rev-parse", f"origin/{ref}")[0].strip()
    cur_head = git(agent_dir, "rev-parse", "HEAD")[0].strip()
    if remote_head == cur_head:
        cons.info("Already up to date.")
        return 0

    cons.info(f"Starting merge: {cur_head[:8]} -> {remote_head[:8]}")
    out, err, code = git(agent_dir, "merge", "--no-edit", f"origin/{ref}")
    if code == 0:
        cons.info("Merge complete.")
        return 0

    cons.warn("Merge conflicts detected. Resolve them with git, then:")
    cons.info(f"  cd {agent_dir}")
    cons.info("  git add <resolved-files>")
    cons.info("  git commit")
    cons.info("  lpb-config status")
    return 1


def cmd_align(agent_dir: str | Path, remote: str, ref: str, cons: Console) -> int:
    """Align settings.json extension pins to latest available tags."""
    settings_path = Path(agent_dir) / "settings.json"
    if not settings_path.is_file():
        cons.error(f"settings.json not found: {settings_path}")
        return 1

    with open(settings_path) as f:
        settings = json.load(f)

    packages = settings.get("packages", [])
    lpb_repos = ["lemonade-pi-plugin", "lpb-memory", "pi-subagents"]

    current_pins = {}
    for pkg in packages:
        if isinstance(pkg, str) and "@" in pkg:
            for name in lpb_repos:
                if f"lpb-stack/{name}@" in pkg:
                    current_pins[name] = pkg.split("@")[-1]

    cons.info("Current extension pins:")
    for name in lpb_repos:
        cons.info(f"  {name}: {current_pins.get(name, '(not pinned)')}")

    cons.info("\nChecking latest tags...")
    latest_tags = {}
    for name in lpb_repos:
        try:
            token = _github_token()
            url = f"https://api.github.com/repos/lpb-stack/{name}/tags"
            headers = {"Accept": "application/vnd.github+json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                tags = json.loads(resp.read())
                if tags:
                    latest_tags[name] = tags[0]["name"]
        except Exception as e:
            cons.warn(f"  {name}: could not fetch ({e})")

    mismatches = []
    for name in lpb_repos:
        cur = current_pins.get(name)
        lat = latest_tags.get(name)
        if cur and lat and cur != lat:
            mismatches.append((name, cur, lat))

    if mismatches:
        cons.warn(f"\nVersion mismatch ({len(mismatches)} extension(s)):")
        for name, cur, lat in mismatches:
            cons.warn(f"  {name}: {cur} → {lat}")

        if confirm("\nUpdate settings.json to latest?"):
            for name, cur, lat in mismatches:
                old = f"git:github.com/lpb-stack/{name}@{cur}"
                new = f"git:github.com/lpb-stack/{name}@{lat}"
                idx = packages.index(old) if old in packages else -1
                if idx >= 0:
                    packages[idx] = new
                    cons.info(f"  {name}: {cur} → {lat}")
            settings["packages"] = packages
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
                f.write("\n")
            cons.info(f"\nUpdated {settings_path}")
            cons.info("Run 'pi update --extensions' to apply")
        else:
            cons.info("Skipped. Run 'lpb-config align' when ready.")
    else:
        cons.info("\nAll extensions up to date")

    cons.info("\nConfig repo status:")
    out, err, code = git(agent_dir, "status", "--porcelain")
    if code == 0 and out.strip():
        cons.warn("Local changes detected:")
        for line in out.strip().split("\n")[:5]:
            cons.info(f"  {line}")
        cons.info("Use 'lpb-config update' to sync (if safe)")
        cons.info("Use 'lpb-config merge' for manual merge")
    else:
        cons.info("  Clean (no local changes)")

    return 0


# ─── Workspace commands ───────────────────────────────────────────────────

def _resolve_repo_path(repo_name: str) -> Path | None:
    """Resolve the actual path of a workspace repo (follow symlinks)."""
    ws_path = WORKSPACE_ROOT / repo_name
    if ws_path.is_symlink():
        target = ws_path.resolve()
        if target.exists():
            return target
    elif (ws_path / ".git").exists() or ws_path.is_dir():
        return ws_path
    return None


def _repo_branch(repo_path: Path) -> str:
    """Get the current branch of a repo."""
    out, _, code = git(repo_path, "branch", "--show-current")
    if code == 0:
        return out.strip()
    return ""


def _repo_head(repo_path: Path) -> str:
    """Get the HEAD commit of a repo."""
    out, _, code = git(repo_path, "rev-parse", "HEAD")
    if code == 0:
        return out.strip()[:8]
    return "?"


def _ensure_branch_tracked(repo_path: Path, branch: str) -> bool:
    """Ensure a remote branch has a local tracking branch. Returns True if success."""
    # Check if local branch exists
    out, _, code = git(repo_path, "rev-parse", "--verify", branch)
    if code == 0:
        return True

    # Check if remote branch exists
    out, _, code = git_auth(repo_path, "ls-remote", "origin", f"refs/heads/{branch}")
    if code != 0 or not out.strip():
        return False

    # Fetch and create local tracking branch
    out, err, code = git_auth(repo_path, "fetch", "origin", branch)
    if code != 0:
        return False

    # Ensure fetch refspec includes all branches (not just one)
    fetch_spec_out, _, _ = git(repo_path, "config", "--get", "remote.origin.fetch")
    fetch_spec = fetch_spec_out.strip()
    if fetch_spec and "refs/heads/*" not in fetch_spec:
        git(repo_path, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        git_auth(repo_path, "fetch", "origin")

    # Create local branch from FETCH_HEAD
    out, err, code = git(repo_path, "checkout", "-b", branch, "FETCH_HEAD")
    if code == 0:
        # Set upstream tracking
        git_auth(repo_path, "fetch", "origin")
        git(repo_path, "branch", "--set-upstream-to", f"origin/{branch}", branch)
        return True

    return False


def cmd_workspace_status(pipeline: str, cons: Console) -> int:
    """Show workspace repo branches and alignment."""
    cons.info(f"Pipeline: {pipeline} (VERSION: {get_version()})")
    cons.info("")

    all_aligned = True
    for name, is_sym, is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        expected = dev_branch if pipeline == "dev" else main_branch
        path = _resolve_repo_path(name)

        if path is None:
            cons.warn(f"  {name}: MISSING")
            all_aligned = False
            continue

        branch = _repo_branch(path)
        head = _repo_head(path)
        symlink = " (symlink)" if is_sym else ""

        if branch == expected:
            cons.info(f"  {name}: {branch}{symlink} ({head}) ✅")
        else:
            cons.warn(f"  {name}: {branch} (expected: {expected}){symlink} ({head}) ❌")
            all_aligned = False

    # Config repo
    config_path = Path(DEFAULT_AGENT_DIR)
    if (config_path / ".git").exists():
        config_expected = "dev" if pipeline == "dev" else "main"
        config_branch = _repo_branch(config_path)
        config_head = _repo_head(config_path)
        if config_branch == config_expected:
            cons.info(f"  config: {config_branch} ({config_head}) ✅")
        else:
            cons.warn(f"  config: {config_branch} (expected: {config_expected}) ({config_head}) ❌")
            all_aligned = False
    else:
        cons.warn("  config: MISSING")
        all_aligned = False

    cons.info("")
    if all_aligned:
        cons.done("All repos aligned with pipeline.")
    else:
        cons.warn("Some repos are misaligned. Run 'lpb-config workspace ensure' to fix.")

    return 0 if all_aligned else 1


def cmd_workspace_sync(pipeline: str, cons: Console) -> int:
    """Create symlinks + git pull current branches."""
    cons.info(f"Syncing workspace for pipeline: {pipeline}")
    cons.info("")

    # Create symlinks for extension repos
    for name, is_sym, is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        if not is_sym:
            continue

        expected = dev_branch if pipeline == "dev" else main_branch
        ext_path = AGENT_GIT / name
        ws_path = WORKSPACE_ROOT / name

        if ext_path.exists():
            # Remove existing symlink or file
            if ws_path.is_symlink() or ws_path.exists():
                if ws_path.is_symlink():
                    ws_path.unlink()
                elif ws_path.is_dir():
                    shutil.rmtree(ws_path)
                else:
                    ws_path.unlink()
            ws_path.symlink_to(ext_path)
            cons.info(f"  {name}: symlink → {ext_path}")

            # Pull latest
            out, err, code = git_auth(ext_path, "pull", "--ff-only")
            if code == 0:
                cons.info(f"  {name}: pulled ✅")
            else:
                cons.warn(f"  {name}: pull failed ({err.strip()[:80]})")
        else:
            cons.warn(f"  {name}: extension not found at {ext_path}")

    # Pull real repos
    for name, is_sym, is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        if is_sym:
            continue
        path = _resolve_repo_path(name)
        if path is None:
            continue

        expected = dev_branch if pipeline == "dev" else main_branch
        out, err, code = git_auth(path, "pull", "--ff-only")
        if code == 0:
            cons.info(f"  {name}: pulled ✅")
        else:
            cons.warn(f"  {name}: pull failed ({err.strip()[:80]})")

    # Pull config repo
    config_path = Path(DEFAULT_AGENT_DIR)
    if (config_path / ".git").exists():
        config_branch = _repo_branch(config_path)
        out, err, code = git(config_path, "pull", "--ff-only")
        if code == 0:
            cons.info(f"  config: pulled ✅")
        else:
            cons.warn(f"  config: pull failed ({err.strip()[:80]})")

    cons.info("")
    cons.done("Workspace sync complete.")
    return 0


def cmd_workspace_ensure(pipeline: str, *, fix: bool = False, cons: Console) -> int:
    """Ensure all workspace repos are on the correct branch for the pipeline.

    If --fix is passed, automatically switch repos to the correct branch.
    """
    cons.info(f"Ensuring workspace alignment for pipeline: {pipeline}")
    if fix:
        cons.info("(auto-fixing misaligned repos)")
    cons.info("")

    all_aligned = True
    actions: list[str] = []

    for name, is_sym, is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        expected = dev_branch if pipeline == "dev" else main_branch
        path = _resolve_repo_path(name)

        if path is None:
            cons.warn(f"  {name}: MISSING")
            all_aligned = False
            actions.append(f"  • Clone {name}")
            continue

        branch = _repo_branch(path)
        if branch == expected:
            cons.info(f"  {name}: {branch} ✅")
            continue

        # Repo is on wrong branch
        all_aligned = False
        if fix:
            # Ensure the target branch is available locally
            if not _ensure_branch_tracked(path, expected):
                cons.error(f"  {name}: could not create/track {expected} branch")
                continue

            # Check for uncommitted changes
            changes_out, _, _ = git(path, "status", "--porcelain")
            if changes_out.strip():
                cons.warn(f"  {name}: uncommitted changes — skipping switch (commit first)")
                continue

            git(path, "checkout", expected)
            new_branch = _repo_branch(path)
            if new_branch == expected:
                cons.info(f"  {name}: {branch} → {expected} ✅ (fixed)")
            else:
                cons.error(f"  {name}: checkout failed (still on {new_branch})")
        else:
            actions.append(f"  • {name}: '{branch}' → '{expected}' (run --fix)")

    # Config repo
    config_path = Path(DEFAULT_AGENT_DIR)
    if (config_path / ".git").exists():
        config_expected = "dev" if pipeline == "dev" else "main"
        config_branch = _repo_branch(config_path)
        if config_branch == config_expected:
            cons.info(f"  config: {config_branch} ✅")
        else:
            all_aligned = False
            if fix:
                changes_out, _, _ = git(config_path, "status", "--porcelain")
                if changes_out.strip():
                    cons.warn(f"  config: uncommitted changes — skipping switch (commit first)")
                else:
                    out, err, code = git(config_path, "checkout", config_expected)
                    if code == 0:
                        cons.info(f"  config: {config_branch} → {config_expected} ✅ (fixed)")
                    else:
                        cons.error(f"  config: checkout failed: {err.strip()[:80]}")
            else:
                actions.append(f"  • config: '{config_branch}' → '{config_expected}' (run --fix)")

    cons.info("")
    if all_aligned:
        cons.done("All repos aligned with pipeline.")
    elif fix:
        cons.warn("Some repos could not be fixed — check errors above.")
    else:
        cons.warn("Misaligned repos found. Actions needed:")
        for action in actions:
            cons.raw(action)
        cons.info("")
        cons.info("Run 'lpb-config workspace ensure --fix' to auto-fix.")

    # ── Generate settings.json from template if missing ────────────────
    if fix:
        agent_dir = Path(DEFAULT_AGENT_DIR)
        template = agent_dir / "settings.json.template"
        settings_file = agent_dir / "settings.json"
        if template.is_file() and not settings_file.is_file():
            version = get_version()
            if pipeline == "main":
                version = version.replace("-dev", "")
            content = template.read_text()
            content = content.replace("__LPB_VERSION__", version)
            settings_file.write_text(content)
            cons.info(f"\nGenerated {settings_file} from template (version: {version})")

    return 0 if all_aligned else 1


# ─── Settings.json helpers ──────────────────────────────────────────────

LPB_EXTENSION_REPOS = ["lemonade-pi-plugin", "lpb-memory", "pi-subagents"]


def _read_settings(agent_dir: str | Path) -> dict | None:
    """Read settings.json from agent dir."""
    path = Path(agent_dir) / "settings.json"
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_settings(agent_dir: str | Path, settings: dict) -> None:
    """Write settings.json to agent dir."""
    path = Path(agent_dir) / "settings.json"
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def _get_pinned_versions(settings: dict) -> dict[str, str]:
    """Extract version pins for LPB extension repos from settings."""
    pins: dict[str, str] = {}
    for pkg in settings.get("packages", []):
        if not isinstance(pkg, str):
            continue
        for name in LPB_EXTENSION_REPOS:
            marker = f"lpb-stack/{name}@"
            if marker in pkg:
                pins[name] = pkg.split("@")[-1]
    return pins


def _update_pinned_versions(settings: dict, target_version: str) -> list[tuple[str, str, str]]:
    """Update LPB extension pins to target_version. Returns list of changes."""
    packages = settings.get("packages", [])
    changes: list[tuple[str, str, str]] = []
    for name in LPB_EXTENSION_REPOS:
        marker = f"git:github.com/lpb-stack/{name}@"
        for i, pkg in enumerate(packages):
            if isinstance(pkg, str) and pkg.startswith(marker):
                old_tag = pkg.split("@")[-1]
                if old_tag != target_version:
                    new_pkg = f"{marker}{target_version}"
                    packages[i] = new_pkg
                    changes.append((name, old_tag, target_version))
    settings["packages"] = packages
    return changes


# ─── Workspace: sync extensions ───────────────────────────────────────────

def cmd_workspace_sync_extensions(pipeline: str, cons: Console) -> int:
    """Sync settings.json extension pins to match current LPB_VERSION."""
    agent_dir = Path(DEFAULT_AGENT_DIR)
    settings = _read_settings(agent_dir)

    if settings is None:
        cons.error(f"settings.json not found: {agent_dir}")
        cons.info("  Run 'lpb-config workspace ensure' to generate from template.")
        return 1

    # Determine target version
    version = get_version()
    # For main pipeline, strip -dev from version
    if pipeline == "main":
        target_version = version.replace("-dev", "")
    else:
        target_version = version

    current_pins = _get_pinned_versions(settings)

    cons.info(f"Pipeline:     {pipeline}")
    cons.info(f"LPB_VERSION:  {version}")
    cons.info(f"Target pins:  {target_version}")
    cons.info("")

    # Check mismatches
    mismatches = []
    for name in LPB_EXTENSION_REPOS:
        cur = current_pins.get(name, "(unpinned)")
        if cur != target_version:
            mismatches.append((name, cur, target_version))

    if not mismatches:
        cons.info("All extension pins already match LPB_VERSION.")
        return 0

    cons.warn(f"Version mismatch ({len(mismatches)} extension(s)):")
    for name, cur, target in mismatches:
        cons.warn(f"  {name}: {cur} → {target}")

    cons.info("")
    if confirm("Update settings.json extension pins?"):
        changes = _update_pinned_versions(settings, target_version)
        _write_settings(agent_dir, settings)
        for name, old, new in changes:
            cons.info(f"  {name}: {old} → {new}")
        cons.info("")
        cons.done("Extension pins updated. Run 'pi update --extensions' to apply.")
    else:
        cons.info("Skipped. Run 'lpb-config workspace sync --extensions' when ready.")

    return 0 if not mismatches else 1


# ─── Validate command ─────────────────────────────────────────────────────

def cmd_validate(pipeline: str, cons: Console) -> int:
    """Validate the entire stack alignment to the current pipeline."""
    version = get_version()
    stack_env = get_stack_env(pipeline)

    cons.info("=" * 60)
    cons.info("  LocalPibox Stack Validation")
    cons.info("=" * 60)
    cons.info("")
    cons.info(f"  Pipeline:  {pipeline}")
    cons.info(f"  VERSION:   {version}")
    cons.info(f"  LPB_PI_REF:     {stack_env.get('LPB_PI_REF', '?')}")
    cons.info(f"  LPB_CONFIG_REF: {stack_env.get('LPB_CONFIG_REF', '?')}")
    cons.info("")

    total_checks = 0
    passed_checks = 0

    def check(label: str, condition: bool, detail: str = "", fix: str = "") -> None:
        nonlocal total_checks, passed_checks
        total_checks += 1
        if condition:
            passed_checks += 1
            cons.info(f"  ✅ {label}")
            if detail:
                cons.raw(f"     {detail}")
        else:
            cons.warn(f"  ❌ {label}")
            if detail:
                cons.warn(f"     {detail}")
            if fix:
                cons.info(f"     Fix: {fix}")

    # ── 1. VERSION file ────────────────────────────────────────────────
    vf = _find_version_file()
    if vf is not None:
        version_on_disk = vf.read_text().strip()
        check(
            "VERSION file exists",
            True,
            f"{vf} = {version_on_disk}",
        )
        version_matches = (pipeline == "dev" and "-dev" in version_on_disk) or \
                          (pipeline == "main" and "-dev" not in version_on_disk)
        check(
            "VERSION matches pipeline",
            version_matches,
            f"VERSION={version_on_disk}, pipeline={pipeline}",
            "Update devstack/VERSION to match pipeline",
        )
    else:
        check("VERSION file exists", False,
              f"checked {_SELF_DIR.parent}, /opt/devstack, {WORKSPACE_ROOT / 'devstack'}",
              "Ensure devstack/VERSION exists")
        check("VERSION matches pipeline", False,
              "no VERSION file found", "Ensure devstack/VERSION exists")

    # ── 2. Config repo ─────────────────────────────────────────────────
    config_path = Path(DEFAULT_AGENT_DIR)
    if (config_path / ".git").exists():
        config_branch = _repo_branch(config_path)
        config_expected = "dev" if pipeline == "dev" else "main"
        check(
            f"Config repo on correct branch",
            config_branch == config_expected,
            f"current={config_branch}, expected={config_expected}",
            "lpb-config reset (or git checkout {config_expected})",
        )
    else:
        check("Config repo exists", False, f"{config_path} not found",
              "lpb-config update")

    # ── 3. Workspace repos ─────────────────────────────────────────────
    cons.info("")
    cons.info("  Workspace repos:")

    for name, is_sym, is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        expected = dev_branch if pipeline == "dev" else main_branch
        path = _resolve_repo_path(name)

        if path is None:
            check(f"  {name} exists", False,
                  f"{WORKSPACE_ROOT / name} not found",
                  f"Clone or create symlink")
            continue

        branch = _repo_branch(path)
        head = _repo_head(path)
        details = f"branch={branch} ({head})"

        if is_sym:
            ws_path = WORKSPACE_ROOT / name
            symlink_ok = ws_path.is_symlink()
            check(f"  {name} symlink", symlink_ok,
                  f"{ws_path} → {ws_path.resolve() if symlink_ok else 'broken'}")
            details = f"symlink ✅" if symlink_ok else f"symlink ❌"

        check(f"  {name} branch", branch == expected, details,
              f"cd {path} && git checkout {expected}")

    # ── 4. Extension repos match workspace ─────────────────────────────
    cons.info("")
    cons.info("  Extension alignment:")

    for name, is_sym, is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        if not is_ext:
            continue

        ws_path = WORKSPACE_ROOT / name
        ext_path = AGENT_GIT / name

        if ws_path.is_symlink():
            # Symlink should point to extension
            resolved = ws_path.resolve()
            check(f"  {name} → extension",
                  resolved == ext_path,
                  f"symlink → {resolved}",
                  f"rm {ws_path} && ln -s {ext_path} {ws_path}")
        elif ext_path.exists():
            # Not symlink — check if they have same commit
            ws_head = _repo_head(ws_path)
            ext_head = _repo_head(ext_path)
            check(f"  {name} in sync",
                  ws_head == ext_head,
                  f"ws={ws_head}, ext={ext_head}",
                  f"cd {ext_path} && git checkout <branch>")

    # ── 5. Stack env alignment ─────────────────────────────────────────
    cons.info("")
    cons.info("  Stack env:")

    pi_ref = stack_env.get("LPB_PI_REF", "")
    config_ref = stack_env.get("LPB_CONFIG_REF", "")
    pi_ref_expected = "lpb-dev" if pipeline == "dev" else "lpb"
    config_ref_expected = "dev" if pipeline == "dev" else "main"

    check(
        f"LPB_PI_REF correct",
        pi_ref == pi_ref_expected,
        f"current={pi_ref}, expected={pi_ref_expected}",
        f"Edit lpb.stack.{pipeline}.env or lpb.stack.env",
    )
    check(
        f"LPB_CONFIG_REF correct",
        config_ref == config_ref_expected,
        f"current={config_ref}, expected={config_ref_expected}",
        f"Edit lpb.stack.{pipeline}.env or lpb.stack.env",
    )

    # ── 6. Settings.json extension pins ────────────────────────────────
    cons.info("")
    cons.info("  Extension pins:")

    # Determine target version for this pipeline
    target_version = version
    if pipeline == "main":
        target_version = version.replace("-dev", "")

    settings_path = config_path / "settings.json"
    settings = _read_settings(config_path)
    if settings:
        current_pins = _get_pinned_versions(settings)

        for pkg_name in LPB_EXTENSION_REPOS:
            pinned_tag = current_pins.get(pkg_name)
            if pinned_tag:
                if pinned_tag == target_version:
                    check(
                        f"  {pkg_name} pinned",
                        True,
                        f"@{pinned_tag} (matches VERSION)",
                    )
                else:
                    check(
                        f"  {pkg_name} pinned",
                        False,
                        f"@{pinned_tag} (expected: {target_version})",
                        "lpb-config workspace sync --extensions",
                    )
            else:
                check(f"  {pkg_name} pinned", False,
                      "not found in settings.json",
                      "lpb-config workspace sync --extensions")
    else:
        check("settings.json exists", False,
              f"{settings_path} not found",
              "Clone config repo or create settings.json")

    # ── 7. pi/lpb vs lpb-dev (informational only) ────────────────────
    cons.info("")
    cons.info("  Fork branch consistency:")

    pi_path = _resolve_repo_path("pi")
    if pi_path:
        lpb_hash_out, _, lpb_code = git(pi_path, "rev-parse", "--verify", "lpb")
        lpbdev_hash_out, _, lpbdev_code = git(pi_path, "rev-parse", "--verify", "lpb-dev")

        if lpb_code == 0 and lpbdev_code == 0:
            lpb_hash = lpb_hash_out.strip()
            lpbdev_hash = lpbdev_hash_out.strip()
            if lpb_hash == lpbdev_hash:
                check(
                    "pi: lpb == lpb-dev",
                    True,
                    f"lpb=lpb-dev ({lpb_hash[:8]})",
                )
            else:
                # lpb-dev ahead of lpb is normal during active development
                # Only warn, don't fail — stable merge to lpb happens when ready
                ahead_out, _, _ = git(pi_path, "rev-list", "--count", "lpb..lpb-dev")
                ahead = ahead_out.strip() or "0"
                cons.info(f"  ℹ️  pi: lpb-dev is {ahead} commit(s) ahead of lpb (normal during dev)")
                cons.raw(f"     lpb={lpb_hash[:8]}, lpb-dev={lpbdev_hash[:8]}")
        else:
            missing = []
            if lpb_code != 0:
                missing.append("lpb")
            if lpbdev_code != 0:
                missing.append("lpb-dev")
            check(
                "pi: lpb & lpb-dev both exist",
                False,
                f"missing local branch(es): {', '.join(missing)}",
                "cd workspace/pi && git fetch origin && git checkout lpb-dev",
            )

    # ── Summary ────────────────────────────────────────────────────────
    cons.info("")
    cons.info("=" * 60)
    pct = (passed_checks / total_checks * 100) if total_checks > 0 else 0
    if passed_checks == total_checks:
        cons.done(f"  All {total_checks} checks passed ✅")
    else:
        cons.warn(f"  {passed_checks}/{total_checks} checks passed ({pct:.0f}%) ❌")
    cons.info("=" * 60)

    return 0 if passed_checks == total_checks else 1


# ─── Memory config commands ──────────────────────────────────────────────

MEMORY_CONFIG_PATH = Path(DEFAULT_AGENT_DIR) / "lpb-memory-config.json"
MEMORY_CONFIG_TEMPLATE = Path(DEFAULT_AGENT_DIR) / "lpb-memory-config.json.template"


def cmd_memory_show(cons: Console) -> int:
    """Show current lpb-memory config."""
    if MEMORY_CONFIG_PATH.is_file():
        data = json.loads(MEMORY_CONFIG_PATH.read_text())
        cons.info("lpb-memory config:")
        cons.info(f"  File: {MEMORY_CONFIG_PATH}")
        cons.info("")
        for key, val in data.items():
            cons.info(f"  {key}: {val}")
    else:
        cons.warn(f"Config not found: {MEMORY_CONFIG_PATH}")
        if MEMORY_CONFIG_TEMPLATE.is_file():
            cons.info("")
            cons.info("Template available, run to generate:")
            cons.info("  lpb-config memory setup --non-interactive")
        else:
            cons.info("")
            cons.info("Extension will use built-in defaults.")
    return 0


def cmd_memory_setup(*, non_interactive: bool = False, cons: Console) -> int:
    """Interactive memory config wizard."""
    if not MEMORY_CONFIG_TEMPLATE.is_file():
        cons.error("Template not found:")
        cons.error(f"  {MEMORY_CONFIG_TEMPLATE}")
        cons.info("Run 'lpb-config update' to fetch latest config repo.")
        return 1

    base = json.loads(MEMORY_CONFIG_TEMPLATE.read_text())

    if non_interactive:
        MEMORY_CONFIG_PATH.write_text(json.dumps(base, indent=2) + "\n")
        cons.info(f"Generated {MEMORY_CONFIG_PATH} from template.")
        cons.info("Run 'lpb-config memory setup' to customize.")
        cons.info("Restart Pi session (/new) to apply.")
        return 0

    cons.info("=" * 50)
    cons.info("  lpb-memory Configuration")
    cons.info("=" * 50)
    cons.info("")

    modes = [
        ("legacy-inject", "Inject memory into every prompt (~4KB, recommended)"),
        ("policy-only", "AI must search memory proactively (saves context)"),
    ]
    cons.info("[1] Memory mode:")
    for i, (mode, desc) in enumerate(modes, 1):
        marker = " ← current" if base.get("memoryMode") == mode else ""
        cons.info(f"  {i}. {mode:<15} {desc}{marker}")
    choice = input("\n  Choice [1]: ").strip() or "1"
    if choice == "2":
        base["memoryMode"] = "policy-only"
        base["memoryPolicyStyle"] = "compact"
    cons.info("")

    transports = [
        ("subprocess", "Offload to separate model (free main session, recommended)"),
        ("direct", "Use main model (faster, blocks main session)"),
    ]
    cons.info("[2] Review transport:")
    for i, (t, desc) in enumerate(transports, 1):
        marker = " ← current" if base.get("reviewTransport") == t else ""
        cons.info(f"  {i}. {t:<15} {desc}{marker}")
    choice = input("\n  Choice [1]: ").strip() or "1"
    if choice == "2":
        base["reviewTransport"] = "direct"
    cons.info("")

    cons.info("[3] Model for background operations:")
    cons.info("  (Leave empty to use main model)")
    cons.info("  Example: qwen3.5-9b-FLM (NPU model)")
    model = input("  Model: ").strip()
    if model:
        base["llmModelOverride"] = model
        base["llmThinkingOverride"] = "low"
    cons.info("")

    cons.info("[4] Context limits (press Enter for defaults):")
    val = input(f"  Memory entries [{base.get('memoryCharLimit', 3000)}]: ").strip()
    if val:
        base["memoryCharLimit"] = int(val)
    val = input(f"  User preferences [{base.get('userCharLimit', 3000)}]: ").strip()
    if val:
        base["userCharLimit"] = int(val)
    val = input(f"  Max failures [{base.get('failureInjectionMaxEntries', 3)}]: ").strip()
    if val:
        base["failureInjectionMaxEntries"] = int(val)
    cons.info("")

    MEMORY_CONFIG_PATH.write_text(json.dumps(base, indent=2) + "\n")
    cons.done(f"Config written to {MEMORY_CONFIG_PATH}")
    cons.info("")
    cons.info("Apply: restart Pi session with /new")
    cons.info("Review: lpb-config memory show")

    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────

def _add_subparser(sub, name: str, help_: str) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help_)
    return p


def main(argv: list[str] | None = None) -> int:
    install_sigpipe_handler()
    parser = argparse.ArgumentParser(
        prog="lpb-config",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment:\n"
            "  AGENT_DIR         Config repo path (default: /home/lpb/.pi/agent)\n"
            "  CONFIG_REMOTE     Git remote URL (default: https://github.com/lpb-stack/config.git)\n"
            "  CONFIG_REF        Branch to track (default: main)\n"
            "  LPB_GITHUB_TOKEN  GitHub token for authenticated git operations\n\n"
            "Pipeline:\n"
            "  Detected from VERSION file or LPB_IMAGE_TAG env var.\n"
            "  Override with --tag dev|main on any command."
        ),
    )
    parser.add_argument(
        "--tag", default=None,
        help="Override pipeline detection (dev|main)",
    )

    sub = parser.add_subparsers(dest="command")

    # Config repo commands
    _add_subparser(sub, "status", "Show config repo commit, remote HEAD, local changes")
    _add_subparser(sub, "update", "Fetch + fast-forward config repo")
    p_reset = _add_subparser(sub, "reset", "Re-clone config repo (with confirmation)")
    p_reset.add_argument("--force", action="store_true", help="skip confirmation")
    _add_subparser(sub, "merge", "Open git merge flow for config repo")
    _add_subparser(sub, "align", "Align settings.json extension pins to latest tags")

    # Memory config subcommand
    p_mem = sub.add_parser("memory", help="Manage lpb-memory extension config")
    mem_sub = p_mem.add_subparsers(dest="memory_command")
    _add_subparser(mem_sub, "show", "Show current lpb-memory config")
    p_mem_setup = _add_subparser(mem_sub, "setup", "Interactive memory config wizard")
    p_mem_setup.add_argument("--non-interactive", action="store_true",
                             help="generate from template without prompts")

    # Validate command
    _add_subparser(sub, "validate", "Validate entire stack alignment to current pipeline")

    # Workspace subcommand group
    p_ws = sub.add_parser("workspace", help="Manage workspace repos")
    ws_sub = p_ws.add_subparsers(dest="workspace_command")
    _add_subparser(ws_sub, "status", "Show workspace repo branches + alignment")
    p_ws_sync = _add_subparser(ws_sub, "sync", "Create symlinks + git pull current branches")
    p_ws_sync.add_argument("--extensions", action="store_true",
                           help="sync settings.json extension pins to LPB_VERSION")
    p_ws_ensure = _add_subparser(ws_sub, "ensure", "Switch repos to correct branches for pipeline")
    p_ws_ensure.add_argument("--fix", action="store_true", help="auto-fix misaligned repos")

    args = parser.parse_args(argv)

    agent_dir = os.environ.get("AGENT_DIR", DEFAULT_AGENT_DIR)
    remote = os.environ.get("CONFIG_REMOTE", DEFAULT_REMOTE)
    ref = os.environ.get("CONFIG_REF", DEFAULT_REF)
    cons = Console()

    if agent_dir == DEFAULT_AGENT_DIR:
        migrate_legacy_layout("/home/lpb/.pi", DEFAULT_AGENT_DIR, cons)

    # Determine pipeline
    pipeline = detect_pipeline(args.tag)

    force = getattr(args, "force", False) or os.environ.get("FORCE") == "1"

    if args.command == "status":
        return cmd_status(agent_dir, remote, ref, cons)
    if args.command == "update":
        return cmd_update(agent_dir, remote, ref, cons)
    if args.command == "reset":
        return cmd_reset(agent_dir, remote, ref, cons, force=force)
    if args.command == "merge":
        return cmd_merge(agent_dir, remote, ref, cons)
    if args.command == "align":
        return cmd_align(agent_dir, remote, ref, cons)
    if args.command == "validate":
        return cmd_validate(pipeline, cons)
    if args.command == "memory":
        if not args.memory_command:
            p_mem.print_help()
            return 1
        if args.memory_command == "show":
            return cmd_memory_show(cons)
        if args.memory_command == "setup":
            non_int = getattr(args, "non_interactive", False)
            return cmd_memory_setup(non_interactive=non_int, cons=cons)
    if args.command == "workspace":
        if not args.workspace_command:
            p_ws.print_help()
            return 1
        if args.workspace_command == "status":
            return cmd_workspace_status(pipeline, cons)
        if args.workspace_command == "sync":
            sync_ext = getattr(args, "extensions", False)
            if sync_ext:
                return cmd_workspace_sync_extensions(pipeline, cons)
            return cmd_workspace_sync(pipeline, cons)
        if args.workspace_command == "ensure":
            fix = getattr(args, "fix", False)
            return cmd_workspace_ensure(pipeline, fix=fix, cons=cons)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
