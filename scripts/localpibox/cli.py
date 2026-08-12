"""Argument-parsing, prompt and fatal-error helpers for LocalPibox tools."""

from __future__ import annotations

import argparse
import signal
import sys
from typing import TextIO

from .log import Console, console


def install_sigpipe_handler() -> None:
    """Restore the default SIGPIPE so piping to tools like ``head`` works.

    Python swallows SIGPIPE and raises BrokenPipeError instead, which prints
    an ugly traceback when output is truncated early (e.g. ``lpb-config status
    | head -3``). Bash scripts don't have this problem; matching their
    behaviour here keeps the ported tools well-behaved in pipelines.
    """
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the shared ``--quiet`` / ``--no-color`` flags to *parser*."""
    group = parser.add_argument_group("common options")
    group.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress informational output (keep warnings/errors)",
    )
    group.add_argument(
        "--no-color", action="store_true",
        help="disable colored output",
    )
    return parser


def console_from_args(args: argparse.Namespace, *, base: Console | None = None) -> Console:
    """Build a Console honouring ``--quiet``/``--no-color`` on *args*."""
    base = base if base is not None else console
    quiet = getattr(args, "quiet", False)
    return Console(
        color=False if getattr(args, "no_color", False) else base.color,
        out=_NullStream() if quiet else base.out,
        err=base.err,
        debug_enabled=base.debug_enabled,
    )


def die(msg: str, hint: str = "", *, code: int = 1, cons: Console | None = None) -> None:
    """Print a fatal error (optionally with a hint) and exit *code*."""
    cons = cons or console
    cons.error(f"Error: {msg}")
    if hint:
        cons.warn(f"  {hint}")
    raise SystemExit(code)


def confirm(
    prompt: str,
    *,
    default: bool = False,
    inp: TextIO | None = None,
    out: TextIO | None = None,
) -> bool:
    """Ask a yes/no question; returns True/False (no trailing newline asked).

    ``default`` is returned when the user answers empty. ``inp``/``out`` are
    injectable for tests (default: ``sys.stdin`` / ``sys.stdout``).
    """
    inp = inp if inp is not None else sys.stdin
    out = out if out is not None else sys.stdout
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        out.write(prompt + suffix)
        out.flush()
        answer = (inp.readline() or "").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


class _NullStream:
    """Duck-typed output sink that discards writes (used for --quiet)."""

    def write(self, s: str) -> int:  # noqa: D102
        return len(s)

    def flush(self) -> None:  # noqa: D102
        pass


__all__ = ["add_common_args", "confirm", "console_from_args", "die", "install_sigpipe_handler"]
