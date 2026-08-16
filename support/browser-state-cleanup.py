#!/usr/bin/env python3
"""browser-state-cleanup — housekeeping for agent-browser session state.

Python port of support/browser-state-cleanup.

Removes session dirs older than ``--max-age-days`` OR when the count exceeds
``--max-count``, keeping the most recent ones. Optionally kills orphaned
Chrome/agent-browser processes first.

State directory: ~/.agent-browser/sessions/ (survives container rebuilds;
only old sessions are pruned).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

_SELF_DIR = Path(__file__).resolve().parent
for _candidate in (_SELF_DIR.parent / "scripts", _SELF_DIR):
    if (_candidate / "lpb-stack").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from lpb-stack.cli import add_common_args, console_from_args, install_sigpipe_handler  # noqa: E402
from lpb-stack.log import Console  # noqa: E402
from lpb-stack.run import run_cmd  # noqa: E402


def session_dirs(state_dir: str | Path) -> list[Path]:
    """Directories directly under *state_dir*, oldest-first-irrelevant order."""
    try:
        return sorted([p for p in Path(state_dir).iterdir() if p.is_dir()])
    except OSError:
        return []


def prune_by_age(
    dirs: list[Path],
    max_age_days: int,
    now: datetime | None = None,
) -> tuple[list[Path], list[Path]]:
    """Split *dirs* into ``(removed, remaining)`` by mtime age.

    Directories whose mtime is older than ``max_age_days`` are removed.
    Directories whose mtime cannot be stat'd are kept.
    """
    now = now or datetime.now()
    cutoff = now - timedelta(days=max_age_days)
    removed: list[Path] = []
    remaining: list[Path] = []
    for d in dirs:
        try:
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
        except OSError:
            remaining.append(d)
            continue
        (removed if mtime < cutoff else remaining).append(d)
    return removed, remaining


def prune_by_count(
    dirs: list[Path],
    max_count: int,
) -> tuple[list[Path], list[Path]]:
    """Trim *dirs* to at most ``max_count``, removing the oldest first."""
    if len(dirs) <= max_count:
        return [], list(dirs)
    by_age = sorted(dirs, key=lambda p: p.stat().st_mtime)
    keep = by_age[-max_count:]
    return [d for d in by_age if d not in keep], keep


def cleanup(
    state_dir: str | Path,
    *,
    max_age_days: int = 7,
    max_count: int = 20,
    remove: bool = True,
    now: datetime | None = None,
) -> tuple[list[Path], list[Path]]:
    """Prune *state_dir*; returns ``(removed, remaining)``.

    Age-based pruning runs first, then count-based pruning on the survivors.
    When ``remove=False`` (dry run) nothing is deleted and the returns still
    describe what *would* be removed/kept.
    """
    dirs = session_dirs(state_dir)
    removed_by_age, dirs = prune_by_age(dirs, max_age_days, now=now)
    removed_by_count, dirs = prune_by_count(dirs, max_count)
    removed = removed_by_age + removed_by_count
    if remove:
        for d in removed:
            shutil.rmtree(d, ignore_errors=True)
        remaining = [d for d in dirs if d.exists()]
    else:
        remaining = list(dirs)
    return removed, remaining


def kill_orphaned(cons: Console) -> None:
    """Best-effort kill of orphaned agent-browser / headless Chrome processes."""
    for pattern in ("agent-browser", "chrome.*--headless"):
        _out, _err, _code = run_cmd(["pkill", "-f", pattern], timeout=10)
    cons.debug("orphaned browser processes cleaned")


def main(argv: list[str] | None = None) -> int:
    install_sigpipe_handler()
    parser = argparse.ArgumentParser(prog="browser-state-cleanup", description=__doc__)
    add_common_args(parser)
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".agent-browser" / "sessions"),
        help="session state directory",
    )
    parser.add_argument("--max-age-days", type=int, default=7, help="prune dirs older than N days")
    parser.add_argument("--max-count", type=int, default=20, help="keep at most N dirs")
    parser.add_argument("--no-kill", action="store_true", help="skip pkill of orphaned browsers")
    parser.add_argument("--dry-run", action="store_true", help="report only; delete nothing")
    args = parser.parse_args(argv)
    cons = console_from_args(args)

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_kill:
        kill_orphaned(cons)

    removed, remaining = cleanup(
        state_dir,
        max_age_days=args.max_age_days,
        max_count=args.max_count,
        remove=not args.dry_run,
    )
    for d in removed:
        cons.info(f"  removed {d.name}" if not args.dry_run else f"  would remove {d.name}")
    cons.info(f"Cleanup complete. Remaining sessions: {len(remaining)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
