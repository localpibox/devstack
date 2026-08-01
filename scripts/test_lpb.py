#!/usr/bin/env python3
"""Test harness for lpb.py — mocks podman/docker, tests every path."""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import textwrap
import types

# ─── Mock podman/docker ──────────────────────────────────────────────────────

MOCK_STATE = {
    "running": False,
    "exists": False,
    "logs": [],
    "image_present": True,
    "interactive": False,  # whether -it was requested
}

_curl_attempts = 0


def mock_podman(args):
    """Mock podman CLI. Stores stdout in MOCK_STATE['_stdout']."""
    MOCK_STATE['_stdout'] = ''
    if len(args) < 2:
        return 0
    cmd = args[1]

    if cmd == "ps":
        has_format = False
        for i, a in enumerate(args):
            if a == "-a":
                MOCK_STATE["exists"] = True
            if a == "--format":
                has_format = True
        names = []
        if MOCK_STATE["exists"] and MOCK_STATE["running"]:
            names = ["localpibox"]
        if has_format:
            MOCK_STATE['_stdout'] = "\n".join(names)
        else:
            if names:
                MOCK_STATE['_stdout'] = "localpibox  Up  ..."
        return 0

    if cmd == "stop":
        if not MOCK_STATE["running"]:
            return 1
        MOCK_STATE["running"] = False
        return 0

    if cmd == "rm":
        if not MOCK_STATE["exists"]:
            return 1
        MOCK_STATE["exists"] = False
        MOCK_STATE["running"] = False
        return 0

    if cmd == "image":
        if len(args) > 2 and args[2] == "inspect":
            return 0 if MOCK_STATE["image_present"] else 1

    if cmd == "pull":
        MOCK_STATE["image_present"] = True
        return 0

    if cmd == "run":
        if MOCK_STATE["running"] and MOCK_STATE["exists"]:
            return 125
        MOCK_STATE["running"] = True
        MOCK_STATE["exists"] = True
        MOCK_STATE["interactive"] = "-it" in args
        MOCK_STATE['_stdout'] = "abc123def456"
        return 0

    if cmd == "logs":
        if MOCK_STATE["exists"]:
            return 0
        return 1

    if cmd == "exec":
        if MOCK_STATE["running"]:
            MOCK_STATE["interactive"] = True
            return 0
        return 1

    return 0


def mock_run(args, **kwargs):
    global _curl_attempts
    if len(args) >= 2 and args[0] in ("podman", "docker"):
        result = mock_podman(args)
        class R:
            stdout = MOCK_STATE.get('_stdout', '')
            stderr = ""
            returncode = result
        return R()
    if "curl" in args:
        _curl_attempts += 1
        if _curl_attempts >= 3:
            class R:
                stdout = "<html></html>"
                stderr = ""
                returncode = 0
            return R()
        class R:
            stdout = ""
            stderr = ""
            returncode = 7
        return R()
    # Real subprocess.run for everything else
    return _subprocess_orig(args, **kwargs)


def mock_which(name):
    if name in ("podman", "docker"):
        return "podman"  # return bare command name, not path
    if name == "curl":
        return "curl"
    return _shutil_orig(name)


def reset_mock():
    """Reset all mock state for a fresh test."""
    MOCK_STATE["running"] = False
    MOCK_STATE["exists"] = False
    MOCK_STATE["image_present"] = True
    MOCK_STATE["interactive"] = False
    MOCK_STATE["_stdout"] = ""
    global _curl_attempts
    _curl_attempts = 0


_module_counter = 0
_subprocess_orig = None
_shutil_orig = None

def make_module():
    """Import lpb.py with all mocks in place. Each call gets unique module name."""
    global _module_counter, _subprocess_orig, _shutil_orig
    _module_counter += 1
    # Save originals ONCE (first call only)
    if _subprocess_orig is None:
        _subprocess_orig = subprocess.run
        _shutil_orig = shutil.which

    # Apply mocks BEFORE importing lpb
    subprocess.run = mock_run
    shutil.which = mock_which

    # Remove LPB_* env vars so tests get clean defaults
    for key in list(os.environ.keys()):
        if key.startswith("LPB_"):
            os.environ.pop(key, None)

    # Use unique name to bypass sys.modules cache
    mod_name = f"lpb_test_{_module_counter}_{id(make_module)}"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lpb_path = os.path.join(script_dir, "lpb.py")
    spec = importlib.util.spec_from_file_location(
        mod_name, lpb_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return mod


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_help():
    print("TEST: --help")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--help"])
    mod.apply_overrides()
    try:
        mod.cmd_help()
    except SystemExit as e:
        assert e.code == 0, f"expected exit 0, got {e.code}"
    print("  PASS\n")


def test_config():
    print("TEST: --config")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--config"])
    mod.apply_overrides()
    mod.cmd_config()
    print("  PASS\n")


def test_port_invalid():
    print("TEST: --port abc → error")
    reset_mock()
    mod = make_module()
    captured = []
    old_stderr = sys.stderr

    class Cap:
        def write(self, s): captured.append(s)
        def flush(self): pass

    sys.stderr = Cap()
    try:
        mod.parse_cli(["--port", "abc"])
        mod.apply_overrides()
        mod.cmd_run()
        assert False, "should have exited"
    except SystemExit:
        err = "".join(captured)
        assert "integer" in err or "error" in err.lower(), f"wrong error: {err}"
    finally:
        sys.stderr = old_stderr
    print("  PASS\n")


def test_remove():
    print("TEST: --remove")
    reset_mock()
    MOCK_STATE["exists"] = True
    mod = make_module()
    mod.parse_cli(["--remove"])
    mod.apply_overrides()
    mod.cmd_remove()
    assert not MOCK_STATE["exists"]
    print("  PASS\n")


def test_stop_running():
    print("TEST: --stop (running)")
    reset_mock()
    MOCK_STATE["exists"] = True
    MOCK_STATE["running"] = True
    mod = make_module()
    mod.parse_cli(["--stop"])
    mod.apply_overrides()
    mod.cmd_stop()
    assert not MOCK_STATE["running"]
    assert not MOCK_STATE["exists"]
    print("  PASS\n")


def test_stop_not_running():
    print("TEST: --stop (not running)")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--stop"])
    mod.apply_overrides()
    mod.cmd_stop()
    print("  PASS\n")


def test_logs_missing():
    print("TEST: --logs (no container)")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--logs"])
    mod.apply_overrides()
    try:
        mod.cmd_logs()
    except SystemExit:
        pass
    print("  PASS\n")


def test_unknown_flag():
    print("TEST: --foo-bar → error")
    reset_mock()
    mod = make_module()
    try:
        mod.parse_cli(["--foo-bar"])
        mod.apply_overrides()
        mod.cmd_run()
        assert False
    except SystemExit as e:
        assert e.code == 1
    print("  PASS\n")


def test_run_welcome():
    print("TEST: lpb (no project → welcome)")
    reset_mock()
    mod = make_module()
    mod.parse_cli([])
    mod.apply_overrides()
    mod.cfg.state_dir = "/tmp/lpb-test-state"
    mod.cfg.browser_dir = "/tmp/lpb-test-browser"
    mod.cfg.open_home = True  # simulate no project
    mod.cmd_run()
    assert MOCK_STATE["running"]
    assert mod.cfg.open_home
    print("  PASS\n")


def test_run_project():
    print("TEST: lpb /tmp (project)")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["/tmp"])
    mod.apply_overrides()
    mod.cfg.state_dir = "/tmp/lpb-test-state"
    mod.cfg.browser_dir = "/tmp/lpb-test-browser"
    mod.cmd_run()
    assert MOCK_STATE["running"]
    assert mod.cfg.project_name == "tmp"
    print("  PASS\n")


def test_run_interactive():
    print("TEST: lpb -i (interactive)")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["-i"])
    mod.apply_overrides()
    mod.cfg.state_dir = "/tmp/lpb-test-state"
    mod.cfg.browser_dir = "/tmp/lpb-test-browser"
    mod.cfg.interactive = True
    mod.cmd_run()
    assert MOCK_STATE["running"]
    assert MOCK_STATE["interactive"]
    print("  PASS\n")


def test_run_port_flag():
    print("TEST: lpb --port 9999 /tmp")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--port", "9999", "/tmp"])
    mod.apply_overrides()
    mod.cfg.state_dir = "/tmp/lpb-test-state"
    mod.cfg.browser_dir = "/tmp/lpb-test-browser"
    mod.cmd_run()
    assert mod.cfg.port == 9999
    assert MOCK_STATE["running"]
    print("  PASS\n")


def test_url_from_resolved_config():
    """Critical: _build_urls() must reflect resolved host:port/token."""
    print("TEST: _build_urls() uses resolved host:port from config")
    reset_mock()
    mod = make_module()
    mod.cfg.host = "0.0.0.0"
    mod.cfg.port = 3000
    mod.cfg.token = "mytoken123"
    mod.cfg.without_token = False
    urls = mod._build_urls()
    health = mod._build_url()
    assert ":3000" in health, f"Health URL missing port: {health}"
    assert "mytoken123" in health, f"Health URL missing token: {health}"
    assert len(urls) >= 1, f"Expected at least 1 URL, got {urls}"
    found_port = any(":3000" in u for u in urls.values())
    found_token = any("mytoken123" in u for u in urls.values())
    assert found_port, f"Port not found in URLs: {urls}"
    assert found_token, f"Token not found in URLs: {urls}"
    print(f"  Health URL: {health}")
    print(f"  Display URLs: {urls}")
    print("  PASS\n")


def test_url_without_token():
    print("TEST: URL without --without-token")
    reset_mock()
    mod = make_module()
    mod.cfg.host = "localhost"
    mod.cfg.port = 8080
    mod.cfg.without_token = True
    url = mod._build_url()
    assert "tkn=" not in url, f"URL should not have token: {url}"
    assert "localhost" in url
    assert ":8080" in url
    print(f"  URL: {url}")
    print("  PASS\n")


def test_url_from_env_override():
    """Simulate .env setting host=0.0.0.0 port=3000, then verify URLs."""
    print("TEST: _build_urls() reflects .env overrides (host=0.0.0.0 port=3000)")
    reset_mock()
    mod = make_module()
    mod.cfg.host = "0.0.0.0"
    mod.cfg.port = 3000
    mod.cfg.token = "devsession"
    urls = mod._build_urls()
    health = mod._build_url()
    assert ":3000" in health
    assert "devsession" in health
    found_port = any(":3000" in u for u in urls.values())
    assert found_port, f"Port 3000 not in display URLs: {urls}"
    print(f"  Health URL: {health}")
    print(f"  Display URLs: {urls}")
    print("  PASS\n")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("lpb.py test suite (mocked podman/docker)")
    print("=" * 60)
    print()

    tests = [
        test_help,
        test_config,
        test_port_invalid,
        test_remove,
        test_stop_running,
        test_stop_not_running,
        test_logs_missing,
        test_unknown_flag,
        test_run_welcome,
        test_run_project,
        test_run_interactive,
        test_run_port_flag,
        test_url_from_resolved_config,
        test_url_without_token,
        test_url_from_env_override,
    ]

    passed = failed = 0
    for t in tests:
        reset_mock()
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed}/{len(tests)} passed, {failed} failed")
    sys.exit(1 if failed else 0)
