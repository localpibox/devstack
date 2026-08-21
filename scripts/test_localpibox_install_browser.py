#!/usr/bin/env python3
"""support/install-browser tests: fetch version, skip existing
chrome, verify, agent-browser install (missing binary / success)."""
from __future__ import annotations

from testharness import run_lpbx_suite, _quiet_console

import io
import json
import os
import shutil
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
        chrome = (tmpdir / f"chrome-{version}" / "chrome-linux64" / "chrome")
        chrome.touch()
        chrome.chmod(0o755)  # properly installed → pure skip
        assert ib.install_chrome(cons) == 0
        assert "already installed" in cons.err.getvalue()


def test_install_browser_chrome_extract_restores_exec_bit(tmpdir):
    """zipfile extraction must leave the chrome binary executable.

    CPython's extractall() drops Unix modes, so install_chrome extracts
    member-by-member and chmods from the zip entry mode.
    """
    import zipfile as _zip
    cons = _quiet_console()
    version = "99.0.0.1"
    zip_path = tmpdir / "chrome-linux64.zip"
    with _zip.ZipFile(zip_path, "w") as zf:
        zi = _zip.ZipInfo("chrome-linux64/chrome")
        zi.external_attr = 0o755 << 16
        zf.writestr(zi, "#!/bin/sh\n")
        zi2 = _zip.ZipInfo("chrome-linux64/manifest.json")
        zi2.external_attr = 0o644 << 16
        zf.writestr(zi2, "{}")

    def fake_retrieve(url, dest):
        shutil.copy(zip_path, dest)

    with mock.patch.object(ib, "CHROME_BASE", tmpdir), \
         mock.patch.object(ib, "fetch_stable_chrome_version", return_value=version), \
         mock.patch.object(ib.urllib.request, "urlretrieve", side_effect=fake_retrieve):
        assert ib.install_chrome(cons) == 0
    bin_path = tmpdir / f"chrome-{version}" / "chrome-linux64" / "chrome"
    assert bin_path.is_file(), "chrome not extracted"
    assert os.access(bin_path, os.X_OK), "chrome binary must be executable after extract"
    assert os.stat(bin_path).st_mode & 0o777 == 0o755, "exec bit must come from the zip entry"


def test_install_browser_chrome_non_executable_repaired(tmpdir):
    """An existing chrome tree without exec bits (older installs) self-heals —
    including chrome_crashpad_handler (its PermissionError 13 kills Chrome
    at startup before DevTools starts)."""
    cons = _quiet_console()
    version = "99.0.0.1"
    chrome = tmpdir / f"chrome-{version}" / "chrome-linux64" / "chrome"
    crashpad = tmpdir / f"chrome-{version}" / "chrome-linux64" / "chrome_crashpad_handler"
    chrome.parent.mkdir(parents=True)
    chrome.touch()  # 0644 — the broken state
    crashpad.touch()
    with mock.patch.object(ib, "CHROME_BASE", tmpdir), \
         mock.patch.object(ib, "fetch_stable_chrome_version", return_value=version):
        assert ib.install_chrome(cons) == 0
    assert os.access(chrome, os.X_OK), "chrome exec bit must be restored"
    assert os.access(crashpad, os.X_OK), "crashpad handler exec bit must be restored"
    assert "exec bits restored" in cons.err.getvalue()


def test_install_browser_verify_no_chrome(tmpdir):
    cons = _quiet_console()
    with mock.patch.object(ib, "CHROME_BASE", tmpdir), \
         mock.patch.object(ib, "SYSTEM_CHROME", tmpdir / "nope"), \
         mock.patch.object(ib, "which", return_value=None):
        assert ib.verify_installation(cons) == 1
        assert "Chrome binary not found" in cons.err.getvalue()


def test_install_browser_verify_non_executable_chrome(tmpdir):
    """verify must report a clean error (not crash) when chrome is 0644."""
    cons = _quiet_console()
    version = "99.0.0.1"
    chrome = tmpdir / f"chrome-{version}" / "chrome-linux64" / "chrome"
    chrome.parent.mkdir(parents=True)
    chrome.touch()  # 0644 — real exec attempt raises PermissionError
    with mock.patch.object(ib, "CHROME_BASE", tmpdir), \
         mock.patch.object(ib, "which", return_value=None):
        assert ib.verify_installation(cons) == 1
        assert "not executable" in cons.err.getvalue()


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
         mock.patch.object(ib.subprocess, "run", side_effect=fake_run), \
         mock.patch.object(ib.Path, "home", return_value=tmpdir):
        assert ib.install_agent_browser(cons) == 0
    assert calls == [
        ["agent-browser", "install"],
        ["agent-browser", "install", "--with-deps"],
    ]
    # container-safe config created in the (mocked) home
    data = json.loads((tmpdir / ".agent-browser" / "config.json").read_text())
    for arg in ("--no-sandbox", "--no-first-run", "--disable-gpu", "--disable-crashpad"):
        assert arg in data["args"].split(","), f"missing {arg}: {data['args']}"


def test_install_browser_config_merges_existing(tmpdir):
    """An existing config.json must keep user args + other keys, and gain
    the missing container-safe args (no duplicates)."""
    cons = _quiet_console()
    (tmpdir / ".agent-browser").mkdir()
    config = tmpdir / ".agent-browser" / "config.json"
    config.write_text(json.dumps({"args": "--headless=new", "hideScrollbars": False}))

    def fake_run(args, **kwargs):
        class FakeResult:
            returncode = 0
        return FakeResult()

    with mock.patch.object(ib, "which", return_value="/bin/agent-browser"), \
         mock.patch.object(ib.subprocess, "run", side_effect=fake_run), \
         mock.patch.object(ib.Path, "home", return_value=tmpdir):
        assert ib.install_agent_browser(cons) == 0
    data = json.loads(config.read_text())
    args = data["args"].split(",")
    assert "--headless=new" in args, f"lost user arg: {data['args']}"
    assert "--no-sandbox" in args, f"missing --no-sandbox: {data['args']}"
    assert args.count("--no-sandbox") == 1, f"duplicated: {data['args']}"
    assert data["hideScrollbars"] is False, "other keys must be preserved"


def test_install_browser_config_replaces_unreadable(tmpdir):
    """A corrupted config.json is overwritten (safe set wins, no crash)."""
    cons = _quiet_console()
    (tmpdir / ".agent-browser").mkdir()
    config = tmpdir / ".agent-browser" / "config.json"
    config.write_text("{not json")

    def fake_run(args, **kwargs):
        class FakeResult:
            returncode = 0
        return FakeResult()

    with mock.patch.object(ib, "which", return_value="/bin/agent-browser"), \
         mock.patch.object(ib.subprocess, "run", side_effect=fake_run), \
         mock.patch.object(ib.Path, "home", return_value=tmpdir):
        assert ib.install_agent_browser(cons) == 0
    data = json.loads(config.read_text())
    assert "--no-sandbox" in data["args"].split(",")


def main() -> int:
    return run_lpbx_suite("install-browser tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
