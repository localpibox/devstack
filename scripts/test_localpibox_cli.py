#!/usr/bin/env python3
"""localpibox.cli tests: confirm defaults/answers, common console
flags (--quiet), die() fatal-error helper."""
from __future__ import annotations

from testharness import run_lpbx_suite, log_mod

import io

from localpibox import cli as cli_mod


def test_confirm_defaults():
    inp = io.StringIO("\n")
    assert cli_mod.confirm("go?", default=True, inp=inp) is True
    inp = io.StringIO("\n")
    assert cli_mod.confirm("go?", default=False, inp=inp) is False


def test_confirm_answers():
    assert cli_mod.confirm("go?", inp=io.StringIO("y\n")) is True
    assert cli_mod.confirm("go?", inp=io.StringIO("Y\n")) is True
    assert cli_mod.confirm("go?", inp=io.StringIO("yes\n")) is True
    assert cli_mod.confirm("go?", inp=io.StringIO("n\n")) is False
    assert cli_mod.confirm("go?", inp=io.StringIO("no\n")) is False


def test_console_from_args_quiet():
    import argparse
    parser = argparse.ArgumentParser()
    cli_mod.add_common_args(parser)
    args = parser.parse_args(["-q", "--no-color"])
    out, err = io.StringIO(), io.StringIO()
    c = cli_mod.console_from_args(args, base=log_mod.Console(color=False, out=out, err=err))
    c.info("hidden"); c.warn("shown")
    assert out.getvalue() == "" and "shown" in err.getvalue()


def test_die_exits():
    try:
        cli_mod.die("boom", cons=log_mod.Console(color=False, err=io.StringIO()))
        assert False, "die should exit"
    except SystemExit as e:
        assert e.code == 1


def main() -> int:
    return run_lpbx_suite("localpibox.cli tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
