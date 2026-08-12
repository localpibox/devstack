#!/usr/bin/env python3
"""lpb-config — Manage the LocalPibox Pi config repo inside the container.

Python port of support/lpb-config.

Usage:
  lpb-config status    — Show current commit, remote HEAD, local changes
  lpb-config update    — Fetch + fast-forward (safe: refuses on local changes)
  lpb-config reset     — Re-clone, destroy local changes (with confirmation)
  lpb-config merge     — Open git merge flow for advanced users

Environment:
  AGENT_DIR         — Config repo path (default: /home/lpb/.pi/agent)
  CONFIG_REMOTE     — Git remote URL (default: https://github.com/localpibox/config.git)
  CONFIG_REF        — Branch to track (default: main)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_SELF_DIR = Path(__file__).resolve().parent
for _c in (_SELF_DIR.parent / "scripts", _SELF_DIR, Path("/opt/pi-support")):
    if (_c / "localpibox").is_dir():
        sys.path.insert(0, str(_c))
        break

from localpibox.cli import confirm, install_sigpipe_handler  # noqa: E402
from localpibox.log import Console  # noqa: E402
from localpibox.run import run_cmd  # noqa: E402

DEFAULT_AGENT_DIR = "/home/lpb/.pi/agent"
DEFAULT_REMOTE = "https://github.com/localpibox/config.git"
DEFAULT_REF = "main"

MIGRATE_KEEP = {".initialized", "ssh-host-keys", "gh-config", "agent"}


def git(dir_: str | Path, *args: str, timeout: int = 120) -> tuple[str, str, int]:
    """Run a git command scoped to *dir_*; returns ``(out, err, code)``."""
    return run_cmd(["git", "-C", str(dir_), *args], timeout=timeout)


def migrate_legacy_layout(pi_root: str | Path, agent_dir: str | Path, cons: Console) -> None:
    """Move legacy ``~/.pi`` root layout contents into ``~/.pi/agent/`` (one-time).

    Preserves the infra markers (.initialized, ssh-host-keys, gh-config, agent/).
    No-op on fresh volumes or already-reshaped layouts.
    """
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


def head_short(agent_dir: str | Path) -> str:
    out, _, _ = git(agent_dir, "rev-parse", "HEAD")
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
            "  AGENT_DIR       Config repo path (default: /home/lpb/.pi/agent)\n"
            "  CONFIG_REMOTE   Git remote URL (default: https://github.com/localpibox/config.git)\n"
            "  CONFIG_REF      Branch to track (default: main)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_subparser(sub, "status", "Show current commit, remote HEAD, local changes")
    _add_subparser(sub, "update", "Fetch + fast-forward (safe: refuses on local changes)")
    p_reset = _add_subparser(sub, "reset", "Re-clone, destroy local changes (with confirmation)")
    p_reset.add_argument("--force", action="store_true", help="skip the confirmation prompt")
    _add_subparser(sub, "merge", "Open git merge flow for advanced users")
    args = parser.parse_args(argv)

    agent_dir = os.environ.get("AGENT_DIR", DEFAULT_AGENT_DIR)
    remote = os.environ.get("CONFIG_REMOTE", DEFAULT_REMOTE)
    ref = os.environ.get("CONFIG_REF", DEFAULT_REF)
    cons = Console()

    if agent_dir == DEFAULT_AGENT_DIR:
        migrate_legacy_layout("/home/lpb/.pi", DEFAULT_AGENT_DIR, cons)

    force = getattr(args, "force", False) or os.environ.get("FORCE") == "1"
    if args.command == "status":
        return cmd_status(agent_dir, remote, ref, cons)
    if args.command == "update":
        return cmd_update(agent_dir, remote, ref, cons)
    if args.command == "reset":
        return cmd_reset(agent_dir, remote, ref, cons, force=force)
    if args.command == "merge":
        return cmd_merge(agent_dir, remote, ref, cons)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
