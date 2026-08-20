"""Workspace operations: repo sync/clone/ensure and settings.json pin helpers.

The workspace mirrors the 6-repo stack under $LPB_WORKSPACE_ROOT (extension
repos live in the agent git area and are symlinked). These operations align
the workspace to a pipeline (dev/main): clone what's missing, create
symlinks, switch branches, fast-forward to origin.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..cli import confirm
from ..log import Console
from ..run import run_cmd
from .gitutil import _git_authenticated, git, git_auth
from .repos import (
    AGENT_GIT,
    DEFAULT_AGENT_DIR,
    LPB_EXTENSION_REPOS,
    WORKSPACE_REPOS,
    WORKSPACE_ROOT,
    _repo_remote,
)
from .version import get_version


# ─── Repo helpers ─────────────────────────────────────────────────────────

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
