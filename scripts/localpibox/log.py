"""Colored console output shared by LocalPibox tools.

Consolidates the ``info``/``warn``/``error``/``done`` helpers that were
copy-pasted across ``start.sh``, ``install-browser.sh``, ``install-openspec.sh``,
``validate.sh`` and ``lpb-config``.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

_RESET = "\033[0m"
_COLORS = {
    "info": "\033[0;32m",    # green
    "warn": "\033[1;33m",    # yellow
    "error": "\033[0;31m",   # red
    "done": "\033[32m",      # green
    "debug": "\033[0;36m",   # cyan
}


def _default_color() -> bool:
    """Color is on by default unless NO_COLOR is set or stdout is not a TTY."""
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class Console:
    """Writes leveled, optionally colored messages to stdout/stderr.

    Pass ``out``/``err`` (and ``color=False``) in tests to capture output.
    """

    def __init__(
        self,
        *,
        color: bool | None = None,
        out: TextIO | None = None,
        err: TextIO | None = None,
        debug_enabled: bool | None = None,
    ) -> None:
        self.color = _default_color() if color is None else color
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self.debug_enabled = bool(
            debug_enabled if debug_enabled is not None else os.environ.get("DEBUG") == "true"
        )

    def _paint(self, level: str, msg: str) -> str:
        return f"{_COLORS[level]}{msg}{_RESET}" if self.color else msg

    def _write(self, level: str, stream: TextIO, msg: str) -> None:
        stream.write(self._paint(level, msg) + "\n")
        stream.flush()

    def info(self, msg: str) -> None:
        self._write("info", self.out, msg)

    def raw(self, msg: str) -> None:
        """Write *msg* to stdout verbatim (no prefix, no color)."""
        self.out.write(msg + "\n")
        self.out.flush()

    def done(self, msg: str) -> None:
        self._write("done", self.out, msg)

    def warn(self, msg: str) -> None:
        self._write("warn", self.err, msg)

    def error(self, msg: str) -> None:
        self._write("error", self.err, msg)

    def debug(self, msg: str) -> None:
        if self.debug_enabled:
            self._write("debug", self.err, msg)


# Module-level singleton + convenience functions (kept for drop-in parity
# with the shell tools' `info()`/`warn()`/`error()` helpers).
console = Console()


def info(msg: str) -> None:
    console.info(msg)


def done(msg: str) -> None:
    console.done(msg)


def warn(msg: str) -> None:
    console.warn(msg)


def error(msg: str) -> None:
    console.error(msg)


def debug(msg: str) -> None:
    console.debug(msg)
