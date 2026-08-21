#!/usr/bin/env python3
"""localpibox.run tests: run_cmd success/failure/missing/timeout,
tool discovery (which/require), container detection."""
from __future__ import annotations

from testharness import run_lpbx_suite

import sys
import time

from localpibox import run as run_mod


def test_run_cmd_success():
    out, err, code = run_mod.run_cmd(["echo", "hello"])
    assert out.strip() == "hello" and code == 0


def test_run_cmd_failure():
    out, err, code = run_mod.run_cmd([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert code == 3


def test_run_cmd_missing_binary():
    out, err, code = run_mod.run_cmd(["/nonexistent/binary", "x"])
    assert code == 127 and "not found" in err


def test_run_cmd_timeout():
    out, err, code = run_mod.run_cmd([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert code == 1 and "timed out" in err


def test_which_and_require():
    assert run_mod.which("definitely_not_a_real_bin_xyz") is None
    assert run_mod.which(sys.executable.split("/")[-1]) is not None
    try:
        run_mod.require("definitely_not_a_real_bin_xyz")
        assert False, "require should raise"
    except RuntimeError:
        pass
    run_mod.require(sys.executable.split("/")[-1])  # must not raise


def test_is_container_returns_bool():
    assert isinstance(run_mod.is_container(), bool)


def main() -> int:
    return run_lpbx_suite("localpibox.run tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
