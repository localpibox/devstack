#!/usr/bin/env python3
"""support/install-browser tests: fetch version, skip existing
chrome, verify, agent-browser install (missing binary / success)."""
from __future__ import annotations

from testharness import run_lpbx_suite, _quiet_console

import io
from unittest import mock
import importlib

ib = importlib.import_module('install-browser')


def test_install_browser_fetch_version():
    payload = b'{"channels":{"Stable":{"version":"130.0.6723.58"}}}'
    with mock.patch.object(ib.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
        assert ib.fetch_stable_chrome_version() == "130.0.6723.58"


def test_install_browser_skips_existing_chrome(tmpdir):
    cons = _quiet_console()
    version = "99.0.0.1"
    with mock.patch.object(ib, "CHROME_BASE", tmpdir), \
         mock.patch.object(ib, "fetch_stable_chrome_version", return_value=version):
        (tmpdir / f"chrome-{version}" / "chrome-linux64").mkdir(parents=True)
        (tmpdir / f"chrome-{version}" / "chrome-linux64" / "chrome").touch()
        assert ib.install_chrome(cons) == 0
        assert "already installed" in cons.err.getvalue()


def test_install_browser_verify_no_chrome(tmpdir):
    cons = _quiet_console()
    with mock.patch.object(ib, "CHROME_BASE", tmpdir), \
         mock.patch.object(ib, "SYSTEM_CHROME", tmpdir / "nope"), \
         mock.patch.object(ib, "which", return_value=None):
        assert ib.verify_installation(cons) == 1
        assert "Chrome binary not found" in cons.err.getvalue()


def test_install_browser_agent_install_missing_binary(tmpdir):
    cons = _quiet_console()
    with mock.patch.object(ib, "which", return_value=None):
        assert ib.install_agent_browser(cons) == 1
        assert "not found" in cons.err.getvalue()


def test_install_browser_agent_install_success(tmpdir):
    cons = _quiet_console()
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        class FakeResult:
            returncode = 0
        return FakeResult()

    with mock.patch.object(ib, "which", return_value="/bin/agent-browser"), \
         mock.patch.object(ib.subprocess, "run", side_effect=fake_run):
        assert ib.install_agent_browser(cons) == 0
    assert calls == [
        ["agent-browser", "install"],
        ["agent-browser", "install", "--with-deps"],
    ]


def main() -> int:
    return run_lpbx_suite("install-browser tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
