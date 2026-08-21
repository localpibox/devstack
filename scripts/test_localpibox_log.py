#!/usr/bin/env python3
"""localpibox.log tests: log levels and streams, color/no-color,
debug gating."""
from __future__ import annotations

from testharness import run_lpbx_suite, log_mod

import io


def test_log_levels_and_streams():
    out, err = io.StringIO(), io.StringIO()
    c = log_mod.Console(color=False, out=out, err=err, debug_enabled=True)
    c.info("i"); c.done("d"); c.warn("w"); c.error("e"); c.debug("g")
    assert out.getvalue() == "i\nd\n"
    assert err.getvalue() == "w\ne\ng\n"


def test_log_color_and_no_color():
    out, err = io.StringIO(), io.StringIO()
    c = log_mod.Console(color=True, out=out, err=err)
    c.info("hi")
    assert "\033[0;32m" in out.getvalue() and "\033[0m" in out.getvalue()
    c2 = log_mod.Console(color=False, out=out, err=err)
    c2.info("plain")
    assert out.getvalue().endswith("plain\n")


def test_log_debug_gated():
    out, err = io.StringIO(), io.StringIO()
    c = log_mod.Console(color=False, out=out, err=err, debug_enabled=False)
    c.debug("hidden")
    assert err.getvalue() == ""


def main() -> int:
    return run_lpbx_suite("localpibox.log tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
