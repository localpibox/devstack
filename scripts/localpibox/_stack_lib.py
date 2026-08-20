"""Shared LocalPibox stack operations library.

Used by the two CLI tools:

  support/lpb-config   — config repo manager (status/update/reset/merge/align/memory)
  support/lpb-devstack — DevOps workspace tool (bump/tag-repos/workspace/validate/release)

Contains everything stack-related so both tools stay thin:

  - git helpers (plain + GitHub-auth aware, repo-scoped and remote-only)
  - workspace repo definitions (WORKSPACE_REPOS / TAG_REPOS) and path constants
  - pipeline detection (dev vs main) and VERSION reading/bumping
  - workspace operations (status / sync / ensure / sync --extensions)
  - full stack validation (cmd_validate)
  - stable-release promotion engine (cmd_release_status / cmd_release_promote)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from .cli import confirm
from .env import parse_env_file
from .log import Console
from .run import run_cmd

# ─── Constants ──────────────────────────────────────────────────────────────

# Devstack repo root (this file lives in <devstack>/scripts/localpibox/).
# In the Docker image this resolves to /opt — harmless, the candidates below
# fall through to /opt/devstack and the workspace.
_DEVSTACK_ROOT = Path(__file__).resolve().parents[2]

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


# ─── Git helpers ───────────────────────────────────────────────────────────

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


# ─── Workspace helpers ────────────────────────────────────────────────────

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


def _repo_remote(name: str) -> str:
    """GitHub remote URL for a stack repo (LPB_STACK_REMOTE_BASE override for tests/offline)."""
    base = os.environ.get("LPB_STACK_REMOTE_BASE", "https://github.com/lpb-stack").rstrip("/")
    return f"{base}/{name}.git"


def _is_dirty(path: Path) -> bool:
    """True when the worktree has uncommitted changes (tracked or untracked)."""
    out, _, _ = git(path, "status", "--porcelain")
    return bool(out.strip())


def _detached_ref(path: Path) -> str:
    """Readable description of a detached HEAD ('detached @ 0.0.52-lpb-dev'); '' on a branch."""
    out, _, code = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or out.strip() != "HEAD":
        return ""
    tag, _, tcode = git(path, "describe", "--tags", "--exact-match")
    if tcode == 0 and tag.strip():
        return f"detached @ {tag.strip()}"
    return f"detached @ {_repo_head(path)}"


def _clone_repo(name: str, dest: Path, expected: str, cons: Console) -> bool:
    """Clone a stack repo at *expected* into *dest*. Returns True on success."""
    remote = _repo_remote(name)
    cons.info(f"  {name}: cloning {remote} (branch: {expected}) ...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out, err, code = run_cmd(
        _git_authenticated(["clone", "-q", "--branch", expected, remote, str(dest)]),
        timeout=600,
    )
    if code != 0:
        cons.error(f"  {name}: clone failed ({(err or out).strip()[:100]})")
        shutil.rmtree(dest, ignore_errors=True)
        return False
    return True


def _sync_repo(name: str, path: Path, expected: str, cons: Console) -> bool:
    """Fetch, align the branch, and fast-forward *path* to origin/*expected*.

    Returns True when the repo ends up on *expected* and up to date.
    Dirty worktrees are left untouched and reported.
    """
    out, err, code = git_auth(path, "fetch", "--prune", "origin", timeout=180)
    if code != 0:
        cons.error(f"  {name}: fetch failed ({(err or out).strip()[:80]})")
        return False

    if _is_dirty(path):
        st, _, _ = git(path, "status", "--short")
        first = (st.strip().splitlines() or ["?"])[0][:60]
        cons.warn(f"  {name}: uncommitted changes ({first}) — skipped (commit or stash first)")
        return False

    branch = _repo_branch(path)
    if branch != expected:
        before = _detached_ref(path) or branch or "?"
        if not _ensure_branch_tracked(path, expected):
            cons.error(f"  {name}: branch '{expected}' not found on origin")
            return False
        out, err, code = git(path, "checkout", "-q", expected)
        if code != 0:
            cons.error(f"  {name}: checkout '{expected}' failed ({err.strip()[:80]})")
            return False
        cons.info(f"  {name}: {before} → {expected}")

    out, err, code = git(path, "merge", "--ff-only", "-q", f"origin/{expected}")
    if code != 0:
        cons.error(f"  {name}: fast-forward to origin/{expected} failed ({err.strip()[:80]})")
        return False

    cons.info(f"  {name}: {expected} @ {_repo_head(path)} ✅")
    return True


# ─── Workspace commands ───────────────────────────────────────────────────

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
        where = branch if branch else (_detached_ref(path) or "(detached)")

        if branch == expected:
            cons.info(f"  {name}: {where}{symlink} ({head}) ✅")
        else:
            cons.warn(f"  {name}: {where} (expected: {expected}){symlink} ({head}) ❌")
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
        cons.warn("Some repos are misaligned. Run 'lpb-devstack workspace ensure' to fix.")

    return 0 if all_aligned else 1


def cmd_workspace_sync(pipeline: str, cons: Console) -> int:
    """Prepare the workspace for *pipeline*:

    - clone missing repos (extension clones + real workspace repos)
    - create/repair symlinks for extension repos
    - check out the pipeline's expected branch (fixes detached-HEAD checkouts
      left behind by pi's pinned-tag extension loads)
    - fast-forward to origin

    Returns 0 only when every repo is on the expected branch and up to date.
    """
    cons.info(f"Preparing workspace for pipeline: {pipeline}")
    cons.info("")

    prepared = True
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    for name, is_sym, _is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        expected = dev_branch if pipeline == "dev" else main_branch

        if is_sym:
            # Extension repos live in the agent git area; the workspace entry is a symlink
            ext_path = AGENT_GIT / name
            ws_path = WORKSPACE_ROOT / name

            if not (ext_path / ".git").exists():
                if not _clone_repo(name, ext_path, expected, cons):
                    prepared = False
                    continue

            if ws_path.is_symlink():
                if ws_path.resolve() != ext_path.resolve():
                    ws_path.unlink()
                    ws_path.symlink_to(ext_path)
                    cons.info(f"  {name}: symlink → {ext_path}")
            elif ws_path.is_dir():
                if (ws_path / ".git").exists():
                    rem, _, _ = git(ws_path, "remote", "get-url", "origin")
                    if rem.strip() == _repo_remote(name):
                        shutil.rmtree(ws_path)
                        ws_path.symlink_to(ext_path)
                        cons.info(f"  {name}: replaced real clone with symlink → {ext_path}")
                    else:
                        cons.error(f"  {name}: {ws_path} is a git repo with a different remote — left untouched")
                        prepared = False
                        continue
                else:
                    cons.error(f"  {name}: {ws_path} exists but is not a git repo — left untouched")
                    prepared = False
                    continue
            else:
                ws_path.symlink_to(ext_path)
                cons.info(f"  {name}: symlink → {ext_path}")

            if not _sync_repo(name, ext_path, expected, cons):
                prepared = False
            continue

        # Real repos live in the workspace root
        path = _resolve_repo_path(name)
        if path is None:
            if not _clone_repo(name, WORKSPACE_ROOT / name, expected, cons):
                prepared = False
                continue
            path = WORKSPACE_ROOT / name

        if not _sync_repo(name, path, expected, cons):
            prepared = False

    # Config repo (the agent dir itself)
    config_path = Path(DEFAULT_AGENT_DIR)
    if (config_path / ".git").exists():
        config_expected = "dev" if pipeline == "dev" else "main"
        if not _sync_repo("config", config_path, config_expected, cons):
            prepared = False
    else:
        cons.warn(f"  config: no git repo at {config_path} — run 'lpb-config update' to install it")
        prepared = False

    cons.info("")
    if prepared:
        cons.done("Workspace prepared.")
        return 0
    cons.warn("Workspace not fully prepared — see messages above.")
    return 1


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

        where = branch if branch else (_detached_ref(path) or "(detached)")

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
                cons.info(f"  {name}: {where} → {expected} ✅ (fixed)")
            else:
                cons.error(f"  {name}: checkout failed (still on {new_branch})")
        else:
            actions.append(f"  • {name}: '{where}' → '{expected}' (run --fix)")

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
                where = config_branch if config_branch else (_detached_ref(config_path) or "(detached)")
                actions.append(f"  • config: '{where}' → '{config_expected}' (run --fix)")

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
        cons.info("Run 'lpb-devstack workspace ensure --fix' to auto-fix.")

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
        cons.info("  Run 'lpb-devstack workspace ensure' to generate from template.")
        return 1

    # Determine target version
    version = get_version()
    if pipeline == "main":
        # Stable version is what CI last wrote on devstack origin/main
        devstack_dir = WORKSPACE_ROOT / "devstack"
        if devstack_dir.is_dir():
            git_auth(devstack_dir, "fetch", "origin", "main", "--quiet", timeout=120)
            out, _, code = git(devstack_dir, "show", "origin/main:VERSION")
            if code == 0 and out.strip():
                version = out.strip()
            else:
                version = version.replace("-dev", "")
        else:
            version = version.replace("-dev", "")
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
        cons.info("Skipped. Run 'lpb-devstack workspace sync --extensions' when ready.")

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
              f"checked {_DEVSTACK_ROOT}, /opt/devstack, {WORKSPACE_ROOT / 'devstack'}",
              "Ensure devstack/VERSION exists")
        check("VERSION matches pipeline", False,
              "no VERSION file found", "Ensure devstack/VERSION exists")

    # ── 2. Config repo ─────────────────────────────────────────────────
    config_path = Path(DEFAULT_AGENT_DIR)
    if (config_path / ".git").exists():
        config_branch = _repo_branch(config_path)
        config_expected = "dev" if pipeline == "dev" else "main"
        check(
            "Config repo on correct branch",
            config_branch == config_expected,
            f"current={config_branch}, expected={config_expected}",
            "lpb-config reset (or git checkout <expected>)",
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
                  "Clone or create symlink")
            continue

        branch = _repo_branch(path)
        head = _repo_head(path)
        details = f"branch={branch} ({head})"

        if is_sym:
            ws_path = WORKSPACE_ROOT / name
            symlink_ok = ws_path.is_symlink()
            check(f"  {name} symlink", symlink_ok,
                  f"{ws_path} → {ws_path.resolve() if symlink_ok else 'broken'}")
            details = "symlink ✅" if symlink_ok else "symlink ❌"

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
        "LPB_PI_REF correct",
        pi_ref == pi_ref_expected,
        f"current={pi_ref}, expected={pi_ref_expected}",
        f"Edit lpb.stack.{pipeline}.env or lpb.stack.env",
    )
    check(
        "LPB_CONFIG_REF correct",
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
                        "lpb-devstack workspace sync --extensions",
                    )
            else:
                check(f"  {pkg_name} pinned", False,
                      "not found in settings.json",
                      "lpb-devstack workspace sync --extensions")
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


# ─── Release (stable promotion) ────────────────────────────────────────────

def _release_repos() -> list[tuple[str, Path, str, str, str]]:
    """All 6 stack repos: (label, path, dev_branch, main_branch, github_repo)."""
    repos: list[tuple[str, Path, str, str, str]] = []
    for name, _is_sym, _is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        repos.append((name, WORKSPACE_ROOT / name, dev_branch, main_branch,
                      f"lpb-stack/{name}"))
    repos.append(("config", Path(DEFAULT_AGENT_DIR), "dev", "main",
                  "lpb-stack/config"))
    return repos


def _repo_release_state(path: Path, dev_branch: str, main_branch: str,
                        cons: Console | None = None) -> dict:
    """Fetch and gather per-repo promotion state (non-destructive)."""
    # Explicit refspecs: some clones (e.g. config) have restricted fetch
    # configs that would not create refs/remotes/origin/<dev>.
    if cons is not None:
        cons.info(f"  fetching {path.name} …")
    git_auth(path, "fetch", "origin", "--quiet",
             f"+refs/heads/{dev_branch}:refs/remotes/origin/{dev_branch}",
             f"+refs/heads/{main_branch}:refs/remotes/origin/{main_branch}",
             timeout=180)
    dirty, _, _ = git(path, "status", "--porcelain")
    state: dict = {
        "dirty": bool(dirty.strip()),
        "local_ahead": 0,        # local stable commits not on origin
        "origin_dev": "?",
        "origin_main": "?",
        "main_behind_by": None,   # commits on dev not on main (None = unknown)
        "diverged": False,        # main has commits not on dev
        "feasibility": "unknown", # aligned|ahead|ff|merge|conflict|unrelated
    }
    out, _, code = git(path, "rev-parse", "--verify", f"origin/{dev_branch}")
    if code == 0:
        state["origin_dev"] = out.strip()[:8]
    out, _, code = git(path, "rev-parse", "--verify", f"origin/{main_branch}")
    if code == 0:
        state["origin_main"] = out.strip()[:8]
        out, _, code = git(path, "rev-list", "--count",
                           f"origin/{main_branch}..{main_branch}")
        if code == 0:
            state["local_ahead"] = int(out.strip())
    if state["origin_dev"] != "?" and state["origin_main"] != "?":
        _, _, code = git(path, "merge-base",
                         f"origin/{main_branch}", f"origin/{dev_branch}")
        if code != 0:
            state["feasibility"] = "unrelated"
        else:
            out, _, code = git(path, "rev-list", "--count",
                               f"origin/{main_branch}..origin/{dev_branch}")
            if code == 0:
                state["main_behind_by"] = int(out.strip())
            out, _, code = git(path, "rev-list", "--count",
                               f"origin/{dev_branch}..origin/{main_branch}")
            if code == 0 and int(out.strip()) > 0:
                state["diverged"] = True
            if state["main_behind_by"] == 0:
                state["feasibility"] = "ahead" if state["diverged"] else "aligned"
            elif state["diverged"]:
                _, _, code = git(path, "merge-tree", "--write-tree",
                                 f"origin/{main_branch}", f"origin/{dev_branch}")
                state["feasibility"] = "merge" if code == 0 else "conflict"
            else:
                state["feasibility"] = "ff"
    return state


def _repo_action(st: dict, rebase: bool) -> tuple[str, str | None]:
    """Decide the promotion action for a repo: (action, skip_reason)."""
    if st["feasibility"] == "unknown":
        return "unknown", "origin refs not found — check repo/remote"
    if st["feasibility"] == "aligned":
        return "no-op", None
    if st["feasibility"] == "ahead":
        return "no-op", ("stable is AHEAD of dev — verify stable's unique "
                         "commits before promoting")
    if st["local_ahead"] > 0:
        return "skip", (f"local stable branch has {st['local_ahead']} unpushed "
                       f"commit(s) — git branch -D <stable> first, then re-run")
    if st["dirty"]:
        return "skip", "local uncommitted changes (commit/stash first)"
    if st["feasibility"] == "conflict":
        return "conflict", "merge conflict — resolve manually"
    if st["feasibility"] == "unrelated":
        if rebase:
            return "rebase", None
        return "unrelated", ("unrelated histories — re-run with --rebase "
                             "(replaces stable with dev history, force-push)")
    return st["feasibility"], None  # ff | merge


def _set_commit_author() -> None:
    """Force LocalPibox author identity for git commits made by this process."""
    os.environ["GIT_AUTHOR_NAME"] = "localpibox"
    os.environ["GIT_AUTHOR_EMAIL"] = "localpibox@gmail.com"
    os.environ["GIT_COMMITTER_NAME"] = "localpibox"
    os.environ["GIT_COMMITTER_EMAIL"] = "localpibox@gmail.com"


def cmd_release_status(cons: Console) -> int:
    """Show stable-release readiness across all 6 stack repos."""
    version = get_version()
    cons.info(f"devstack VERSION: {version}  (pipeline: "
              f"{'dev' if '-dev' in version else 'main'})")
    cons.info("")
    problems = 0
    for label, path, dev_b, main_b, gh in _release_repos():
        if not path.is_dir():
            cons.error(f"{label:18s} repo missing at {path}")
            problems += 1
            continue
        st = _repo_release_state(path, dev_b, main_b, cons)
        feas = st["feasibility"]
        if feas == "unknown":
            mark, note = "❌", "origin refs not found (fetch failed?)"
            problems += 1
        elif feas == "aligned":
            mark, note = "✅", "aligned"
        elif feas == "ahead":
            mark, note = "⚠️", f"{main_b} is AHEAD of dev — check its unique commits"
            problems += 1
        elif feas == "ff":
            mark, note = "✅", f"{main_b} {st['main_behind_by']} behind → fast-forward"
        elif feas == "merge":
            mark, note = "✅", f"{main_b} {st['main_behind_by']} behind → clean 3-way merge"
        elif feas == "conflict":
            mark, note = "⚠️", "merge conflict — resolve manually"
            problems += 1
        else:  # unrelated
            mark, note = "⚠️", ("unrelated histories → promote --rebase "
                                "(replaces history, force-push)")
            problems += 1
        if st["dirty"]:
            note += "; LOCAL DIRTY (uncommitted changes will not be promoted)"
            problems += 1
        if st["local_ahead"] > 0:
            note += (f"; LOCAL {main_b} AHEAD ({st['local_ahead']} unpushed "
                     f"commit(s) — delete local branch to promote)")
            problems += 1
        cons.info(f"{mark} {label:18s} {gh}")
        cons.info(f"     {dev_b}={st['origin_dev']}  {main_b}={st['origin_main']}  {note}")
    cons.info("")
    if problems:
        cons.warn(f"{problems} issue(s) — see above before promoting.")
    else:
        cons.done("All repos ready for stable promotion.")
    return 0


def cmd_release_promote(*, assume_yes: bool, dry_run: bool, rebase: bool,
                        cons: Console) -> int:
    """Promote dev branches to stable branches across all 6 stack repos.

    Per repo (merge ff or clean 3-way): reset local stable branch to origin,
    merge origin/<dev>. Unrelated histories (re-initialized stable branch):
    with --rebase, replace stable with the dev history (force-push) — the
    first-release mode. On conflict: leave the repo untouched, report.
    devstack only: strip the -dev VERSION suffix on the stable branch.
    Then push all successfully promoted repos. CI (main pipeline) then
    builds/tags once VERSION changes on main (manual tagging — CI never
    bumps; if main's VERSION already matches, re-tag with
    `lpb-devstack tag-repos --branch main`).
    """
    _set_commit_author()
    version = get_version()
    if "-dev" not in version:
        cons.warn(f"local devstack VERSION={version} has no -dev suffix — "
                  "run 'git pull --ff-only' on dev first if possible.")

    # ── Pre-flight ──
    entries: list[tuple[str, Path, str, str, str, dict]] = []
    ok = True
    for label, path, dev_b, main_b, gh in _release_repos():
        if not path.is_dir():
            cons.error(f"{label}: repo missing at {path}")
            ok = False
            continue
        st = _repo_release_state(path, dev_b, main_b, cons)
        entries.append((label, path, dev_b, main_b, gh, st))
        if st["origin_main"] == "?":
            cons.error(f"{label}: origin/{main_b} does not exist")
            ok = False
    if not ok:
        cons.error("Pre-flight failed — aborting, nothing was changed.")
        return 1

    cons.info("")
    cons.info("Stable release plan:")
    for label, _p, dev_b, main_b, gh, st in entries:
        action, skip_reason = _repo_action(st, rebase)
        if skip_reason:
            cons.warn(f"  {gh}: SKIP — {skip_reason}")
        else:
            cons.info(f"  {gh}: {action} (origin/{dev_b} → {main_b})")
    cons.info("  devstack: strip -dev from VERSION on main")
    if dry_run:
        cons.info("")
        cons.info("Dry run — nothing was changed.")
        return 0
    cons.info("")
    if rebase:
        rebased_plan = [gh for _l, _p, _db, _mb, gh, st in entries
                        if _repo_action(st, rebase)[0] == "rebase"]
        msg = (f"Promote to stable branches and push? "
               f"(FORCE-PUSH on: {', '.join(rebased_plan)})")
    else:
        msg = "Promote to stable branches and push?"
    if not assume_yes and not confirm(msg):
        cons.info("Aborted.")
        return 1

    # ── Merge ──
    failures: list[str] = []
    skipped: list[str] = []
    rebased: list[str] = []
    for label, path, dev_b, main_b, gh, st in entries:
        cons.info(f"── {label} ──")
        action, skip_reason = _repo_action(st, rebase)
        if skip_reason:
            cons.warn(f"  {label}: {skip_reason}")
            skipped.append(label)
            continue
        if action == "no-op":
            cons.info(f"  {label}: already aligned — nothing to do")
            continue
        if action == "rebase":
            out, err, code = git(path, "checkout", "-q", "-B", main_b,
                                 f"origin/{dev_b}")
            if code != 0:
                cons.error(f"  {label}: rebase checkout failed: "
                           f"{err.strip() or out.strip()}")
                failures.append(label)
                continue
            rebased.append(label)
            cons.info(f"  {label}: {main_b} reset to origin/{dev_b} "
                      f"(first-release mode, will force-push)")
            continue
        # ff / merge
        out, err, code = git(path, "checkout", "-q", "-B", main_b, f"origin/{main_b}")
        if code != 0:
            cons.error(f"  {label}: checkout {main_b} failed: {err.strip() or out.strip()}")
            failures.append(label)
            continue
        out, err, code = git(path, "merge", "--no-edit", f"origin/{dev_b}")
        if code != 0:
            git(path, "merge", "--abort")
            git(path, "reset", "-q", "--hard", f"origin/{main_b}")
            cons.error(f"  {label}: MERGE CONFLICT — {main_b} left untouched, "
                       "resolve manually")
            failures.append(label)
            continue
        if "up to date" in (out + err):
            cons.info(f"  {label}: already up to date")
        else:
            cons.info(f"  {label}: merged origin/{dev_b} → {main_b} ({action})")

    # ── devstack VERSION: strip -dev on main ──
    for label, path, dev_b, main_b, gh, st in entries:
        if label != "devstack" or label in failures or label in skipped:
            continue
        vf = path / "VERSION"
        current = vf.read_text().strip()
        if current.endswith("-dev"):
            stable = current[: -len("-dev")]
            vf.write_text(stable + "\n")
            git(path, "add", "VERSION")
            cons.info(f"  devstack: committing VERSION {current} → {stable} "
                      f"on {main_b} …")
            cons.info("  (pre-commit hook runs the test suite — may take a "
                      "while)")
            out, err, code = git(path, "commit", "-m",
                                 f"release: {stable} — stable branch promoted "
                                 f"from dev",
                                 timeout=600)
            if code != 0:
                detail = err.strip() or out.strip() or "unknown error"
                cons.error(f"  devstack: VERSION commit failed: {detail}")
                cons.error("  State: main has the merged dev content; the "
                           "VERSION change is STAGED (not committed).")
                cons.error(
                    f"  Recover: cd {path} && "
                    f"git commit -m 'release: {stable} — stable branch promoted "
                    f"from dev' && git push origin {main_b}"
                )
                failures.append("devstack")
            else:
                cons.info(f"  devstack: VERSION {current} → {stable} (on {main_b})")

    # ── Push ──
    cons.info("")
    cons.info("Pushing stable branches...")
    for label, path, dev_b, main_b, gh, st in entries:
        if label in failures or label in skipped:
            continue
        action, _ = _repo_action(st, rebase)
        if action == "no-op":
            continue
        push_args = ["push", "origin", main_b]
        if label in rebased:
            push_args = ["push", "--force-with-lease", "origin", main_b]
        cons.info(f"  pushing {gh}:{main_b} …")
        out, err, code = git_auth(path, *push_args, timeout=180)
        if code != 0:
            cons.error(f"  {label}: push failed: {err.strip() or out.strip()}")
            failures.append(label)
        else:
            force = " (force)" if label in rebased else ""
            cons.info(f"  pushed {gh}:{main_b}{force}")

    # ── Summary ──
    cons.info("")
    cons.info("Result:")
    for label, path, dev_b, main_b, gh, st in entries:
        if label in failures:
            cons.error(f"  ❌ {gh:35s} failed")
        elif label in skipped:
            cons.warn(f"  ⏭ {gh:35s} skipped")
        elif _repo_action(st, rebase)[0] == "no-op":
            cons.info(f"  ✅ {gh:35s} aligned (no change)")
        else:
            force = " (force)" if label in rebased else ""
            cons.info(f"  ✅ {gh:35s} promoted{force}")
    if skipped:
        cons.warn(f"Skipped: {', '.join(skipped)} — see notes above")
    if failures:
        cons.error(f"Failed: {', '.join(failures)}")
        cons.error("Stable release INCOMPLETE — complete the failing repo "
                   "(recovery steps above), then re-run "
                   "'lpb-devstack release promote' (already-promoted repos "
                   "fast-forward or no-op).")
        return 1
    stable_version = (version[:-len("-dev")] if version.endswith("-dev") else version)
    cons.done(f"Promoted all 6 repos. main's VERSION is now {stable_version}.")
    cons.info(f"CI (main pipeline) now builds :{stable_version}-* / :main-* / :latest-*")
    cons.info("and tags the 5 repos at the stable branches.")
    cons.info("After CI passes:")
    cons.info("  1. lpb-devstack --tag main workspace sync --extensions")
    cons.info("  2. pi update --extensions")
    cons.info(f"  (If CI's tag-repos didn't run: lpb-devstack tag-repos --branch main --version {stable_version})")
    return 0


__all__ = [
    "AGENT_GIT",
    "DEFAULT_AGENT_DIR",
    "DEFAULT_REMOTE",
    "DEFAULT_REF",
    "EXTENSION_REPOS",
    "LPB_EXTENSION_REPOS",
    "MIGRATE_KEEP",
    "MEMORY_CONFIG_PATH",
    "MEMORY_CONFIG_TEMPLATE",
    "TAG_REPOS",
    "VERSION_RE",
    "WORKSPACE_REPOS",
    "WORKSPACE_ROOT",
    "bump_version",
    "cmd_release_promote",
    "cmd_release_status",
    "cmd_validate",
    "cmd_workspace_ensure",
    "cmd_workspace_status",
    "cmd_workspace_sync",
    "cmd_workspace_sync_extensions",
    "detect_pipeline",
    "expected_branch",
    "get_stack_env",
    "get_version",
    "git",
    "git_auth",
    "git_remote",
    "migrate_legacy_layout",
    "parse_version",
    "_find_version_file",
    "_github_token",
]
