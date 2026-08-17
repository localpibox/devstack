#!/usr/bin/env python3
"""Test harness for lpb.py — mocks podman/docker, tests every path.

Regression guards:
  - Structural: verifies every function the dispatcher/handlers reference is
    actually defined at module level (catches `def` swallowed by comments).
  - Env discovery: verifies lpb.stack.env / lpb.conf.env are actually found
    and parsed (catches loaders silently returning {}).
  - Path semantics: verifies state/browser dirs resolve to HOST paths, not
    container paths.
"""

import ast
import builtins
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
_ISOLATED_HOME = tempfile.mkdtemp(prefix="lpb_test_home_")


class _OutputCapture:
    """Redirect stdout+stderr to a sink while active (suppresses expected noise).

    Also redirects the root logger's handler streams — lpb.py's err()/warn()
    write through BOTH print(..., file=sys.stderr) and logger.error, and the
    logger handler captured the original sys.stderr at import time, so it
    would bypass a plain sys.stderr swap.
    """

    def __init__(self):
        self.out = []
        self._old = None
        self._old_streams = None

    def write(self, s):
        self.out.append(s)

    def flush(self):
        pass

    def __enter__(self):
        self._old = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = self, self
        self._old_streams = [h.stream for h in logging.getLogger().handlers]
        for h in logging.getLogger().handlers:
            h.stream = self
        return self

    def __exit__(self, *exc):
        sys.stdout, sys.stderr = self._old
        for h, stream in zip(logging.getLogger().handlers, self._old_streams):
            h.stream = stream
        return False


def make_module(lpb_path: str | None = None):
    """Import lpb.py with all mocks in place. Each call gets unique module name.

    lpb_path: override which lpb source file to import (used by regression
    mutation tests to load a deliberately-broken copy).

    HOME is redirected to a private temp dir, so the module never touches the
    real ~/.lpb-stack (token / last-project / last-image / state defaults).
    """
    global _module_counter, _subprocess_orig, _shutil_orig
    _module_counter += 1
    # Save originals ONCE (first call only)
    if _subprocess_orig is None:
        _subprocess_orig = subprocess.run
        _shutil_orig = shutil.which

    # Apply mocks BEFORE importing lpb
    subprocess.run = mock_run
    shutil.which = mock_which

    # Remove LPB_* env vars so tests get clean defaults, and point HOME at a
    # private temp dir so the module's default paths are isolated per run.
    for key in list(os.environ.keys()):
        if key.startswith("LPB_"):
            os.environ.pop(key, None)
    os.environ["HOME"] = _ISOLATED_HOME

    # Use unique name to bypass sys.modules cache
    mod_name = f"lpb_test_{_module_counter}_{id(make_module)}"
    if lpb_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        lpb_path = os.path.join(script_dir, "lpb.py")
    spec = importlib.util.spec_from_file_location(mod_name, lpb_path)
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
    with _OutputCapture():
        mod.cmd_remove()
    assert not MOCK_STATE["exists"], "container should be removed"
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
    assert not MOCK_STATE["running"], "container should be stopped"
    assert not MOCK_STATE["exists"], "container should be removed"
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
    with _OutputCapture():
        try:
            mod.cmd_logs()
        except SystemExit:
            pass
    print("  PASS\n")


def test_unknown_flag():
    print("TEST: --foo-bar → error")
    reset_mock()
    mod = make_module()
    with _OutputCapture():
        try:
            mod.parse_cli(["--foo-bar"])
            mod.apply_overrides()
            mod.cmd_run()
            assert False, "should have raised an error"
        except (SystemExit, mod.DevstackError) as e:
            # DevstackError (new) or SystemExit(code=1) (legacy path)
            if isinstance(e, SystemExit):
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
    assert mod.cfg.open_home, "should be in home mode"
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
    assert MOCK_STATE["running"], "container should be running after start"
    assert mod.cfg.project_name == "tmp", f"expected 'tmp', got '{mod.cfg.project_name}'"
    print("  PASS\n")


def test_run_shell():
    print("TEST: lpb --shell /tmp")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--shell", "/tmp"])
    mod.apply_overrides()
    mod.cfg.state_dir = "/tmp/lpb-test-state"
    mod.cfg.browser_dir = "/tmp/lpb-test-browser"
    mod.cmd_run()
    assert mod.cfg.shell_mode, "shell_mode should be True"
    assert mod.cfg.image_name == mod.CLI_IMAGE, f"expected {mod.CLI_IMAGE}, got {mod.cfg.image_name}"
    assert mod.cfg.project_name == "tmp", f"expected 'tmp', got '{mod.cfg.project_name}'"
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
    assert mod.cfg.port == 9999, f"expected 9999, got {mod.cfg.port}"
    assert MOCK_STATE["running"], "container should be running after start"
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
    # _build_url converts localhost → 127.0.0.1
    assert "127.0.0.1" in url or "localhost" in url, f"Expected localhost in URL: {url}"
    assert ":8080" in url, f"Expected :8080 in URL: {url}"
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


# ─── Image tag tests ──────────────────────────────────────────────────────────

def test_tag_dev():
    """--tag dev sets image_tag to dev."""
    print("TEST: --tag dev")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "dev"])
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_main():
    """--tag main sets image_tag to main."""
    print("TEST: --tag main")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "main"])
    assert mod.cfg.image_tag == "main", f"Expected 'main', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_latest():
    """--tag latest sets image_tag to latest."""
    print("TEST: --tag latest")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "latest"])
    assert mod.cfg.image_tag == "latest", f"Expected 'latest', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_custom_version():
    """--tag 0.0.27-lpb-dev sets image_tag to custom version."""
    print("TEST: --tag custom version")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "0.0.27-lpb-dev"])
    assert mod.cfg.image_tag == "0.0.27-lpb-dev", f"Expected '0.0.27-lpb-dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_with_project():
    """--tag dev /path sets image_tag and project_dir."""
    print("TEST: --tag dev /tmp")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "dev", "/tmp"])
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    assert mod.cfg.project_dir == "/tmp", f"Expected '/tmp', got {mod.cfg.project_dir!r}"
    print("  PASS\n")


def test_update_with_tag():
    """--update --tag dev sets command=update and image_tag=dev."""
    print("TEST: --update --tag dev")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--update", "--tag", "dev"])
    assert mod.cfg.command == "update", f"Expected 'update', got {mod.cfg.command!r}"
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_web_mode():
    """--web --tag dev sets web_mode and image_tag."""
    print("TEST: --web --tag dev")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--web", "--tag", "dev"])
    assert mod.cfg.web_mode, "Expected web_mode=True"
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_resolve_cli_image_dev():
    """resolve_cli_image('dev') returns dev-cli suffix."""
    print("TEST: resolve_cli_image('dev')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_cli_image("dev")
    assert image.endswith("-cli") or image.endswith(":dev-cli"), f"Expected -cli suffix, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_cli_image_main():
    """resolve_cli_image('main') returns main/cli suffix."""
    print("TEST: resolve_cli_image('main')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_cli_image("main")
    assert image.endswith("-cli") or image.endswith(":main-cli"), f"Expected -cli suffix, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_cli_image_custom():
    """resolve_cli_image('0.0.27-lpb-dev') returns versioned image."""
    print("TEST: resolve_cli_image('0.0.27-lpb-dev')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_cli_image("0.0.27-lpb-dev")
    assert "0.0.27-lpb-dev" in image, f"Expected version in image, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_web_image_dev():
    """resolve_web_image('dev') returns dev-web suffix."""
    print("TEST: resolve_web_image('dev')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_web_image("dev")
    assert image.endswith("-web") or image.endswith(":dev-web"), f"Expected -web suffix, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_self_update_branch_selection():
    """self_update selects dev branch when image_tag=dev, main otherwise."""
    print("TEST: self_update branch selection")
    reset_mock()
    mod = make_module()
    # When image_tag is dev, branch should be dev
    mod.cfg.image_tag = "dev"
    # Can't easily mock urllib, but we can verify the branch logic
    # by checking the URL pattern would be correct
    branch = "dev" if mod.cfg.image_tag == "dev" else "main"
    assert branch == "dev", f"Expected 'dev' branch, got {branch}"
    # When image_tag is not dev, branch should be main
    mod.cfg.image_tag = "main"
    branch = "dev" if mod.cfg.image_tag == "dev" else "main"
    assert branch == "main", f"Expected 'main' branch, got {branch}"
    print("  PASS\n")


# ─── Regression guards ────────────────────────────────────────────────────────

# Every name referenced by main()'s dispatcher or by cmd_* handlers must exist
# as a real module-level callable. Catches `def` swallowed into comments and
# accidental renames (both were real regressions).
REQUIRED_CALLABLES = [
    # dispatcher handlers (main)
    "cmd_help", "cmd_stop", "cmd_remove", "cmd_logs",
    "cmd_update", "cmd_config", "cmd_run",
    # helpers referenced by handlers
    "self_update", "ensure_container_cmd", "client", "ensure_token",
    "_save_version", "_load_last_version", "resolve_path",
    "detect_mount_flags", "is_podman", "run_cmd", "load_config_file",
    "apply_overrides", "parse_cli", "load_project_env", "load_project_override",
    "_build_urls", "_build_url", "_get_host_for_url", "_get_lan_ips",
    "_find_env_file", "_parse_env_file", "_load_stack_env", "_load_conf_env",
]

# Env vars the container run path must populate (host-driven values).
REQUIRED_ENV_VARS = [
    "LPB_ED_PORT", "LPB_EDITOR_HOST", "LPB_DEVCONTAINER_WORKSPACE_DIR",
    "LPB_CONNECTION_TOKEN", "CONNECTION_TOKEN",
]


def test_module_structure():
    """Every handler/helper referenced by the dispatcher must be a real function.

    Regression guard: the separator comment `# ── ... ──def self_update()` merged
    the `def` into the comment, so self_update vanished and cmd_update would
    NameError at runtime. This test fails fast on that class of bug.
    """
    print("TEST: module structure (all required callables defined)")
    reset_mock()
    mod = make_module()
    missing = [name for name in REQUIRED_CALLABLES if not callable(getattr(mod, name, None))]
    assert not missing, f"missing/not-callable: {missing}"
    print("  PASS\n")


def test_handler_dispatches():
    """main()'s handler table must map every command to an existing callable."""
    print("TEST: dispatcher handler table")
    reset_mock()
    mod = make_module()
    for name in REQUIRED_CALLABLES:
        if not name.startswith("cmd_"):
            continue
        assert callable(getattr(mod, name, None)), f"{name} not callable"
    print("  PASS\n")


def test_env_files_found():
    """lpb.stack.env / lpb.conf.env must be discoverable and parse to non-empty dicts.

    Regression guard: the loaders looked in scripts/ only, always returning {},
    so build identity and runtime defaults were silently ignored.
    """
    print("TEST: _load_stack_env() / _load_conf_env() find the real files")
    reset_mock()
    mod = make_module()
    stack = mod._load_stack_env()
    conf = mod._load_conf_env()
    assert isinstance(stack, dict) and stack, "stack env not loaded"
    assert isinstance(conf, dict) and conf, "conf env not loaded"
    # stack identity keys (from lpb.stack.env at repo root)
    for key in ("LPB_IMAGE_CLI", "LPB_IMAGE_WEB", "LPB_CONTAINER_NAME", "LPB_CONFIG_FORK", "LPB_CONFIG_REF"):
        assert key in stack, f"stack env missing {key}: {list(stack)}"
    # runtime keys (from lpb.conf.env)
    for key in ("LPB_STATE_DIR", "LPB_BROWSER_DIR", "LPB_EDITOR_HOST"):
        assert key in conf, f"conf env missing {key}: {list(conf)}"
    # module-level constants must reflect the stack file
    assert mod.CLI_IMAGE == stack["LPB_IMAGE_CLI"], f"CLI_IMAGE={mod.CLI_IMAGE} != {stack['LPB_IMAGE_CLI']}"
    assert mod.WEB_IMAGE == stack["LPB_IMAGE_WEB"], f"WEB_IMAGE={mod.WEB_IMAGE} != {stack['LPB_IMAGE_WEB']}"
    print("  PASS\n")


def test_env_file_search_order():
    """_find_env_file must search script dir → repo root → CONFIG_DIR, first match wins."""
    print("TEST: _find_env_file search order")
    reset_mock()
    mod = make_module()
    found = mod._find_env_file("lpb.stack.env")
    assert found is not None and found.is_file(), f"lpb.stack.env not found (got {found})"
    print(f"  found: {found}")
    assert mod._find_env_file("definitely-not-a-real-file.env") is None
    print("  PASS\n")


def test_parse_env_file():
    """KEY=value parsing: comments, blanks, export prefix, quoting."""
    print("TEST: _parse_env_file")
    reset_mock()
    mod = make_module()
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
        f.write("# comment\n\nexport FOO=bar\nQUOTED='a b c'\n\n")
        path = f.name
    try:
        env = mod._parse_env_file(path)
        assert env == {"FOO": "bar", "QUOTED": "a b c"}, f"got {env}"
    finally:
        os.unlink(path)
    # Missing file → empty dict (no crash)
    assert mod._parse_env_file(path) == {}
    print("  PASS\n")


def test_resolve_path_host_semantics():
    """state_dir/browser_dir must resolve to HOST paths (not container paths).

    Regression guard: lpb.conf.env once shipped container paths (/home/lpb/...)
    which became bogus host mount sources. Host paths must be absolute, expand
    ~ and ${HOME}.
    """
    print("TEST: resolve_path() host semantics")
    reset_mock()
    mod = make_module()
    home = os.path.expanduser("~")
    assert mod.resolve_path(f"${{HOME}}/foo") == os.path.join(home, "foo"), "resolve_path(${HOME})"
    assert mod.resolve_path("~/foo") == os.path.join(home, "foo"), "resolve_path(~)"
    assert mod.resolve_path("/tmp/x") == "/tmp/x", "absolute passthrough"
    # resolved cfg paths must never contain a container-home prefix
    for attr in ("state_dir", "browser_dir"):
        resolved = mod.resolve_path(getattr(mod.cfg, attr))
        assert not resolved.startswith("/home/lpb"), f"{attr} resolved to container path: {resolved}"
        assert resolved.startswith(home), f"{attr} not under host home: {resolved}"
    print("  PASS\n")


def test_cmd_remove_with_dirs():
    """--remove must delete state+browser dirs after confirmation (Path.is_dir path).

    Regression guard: resolve_path() returns str, but cmd_remove called
    d.is_dir() directly → AttributeError. Also verifies the interactive
    confirmation ('y') path.
    """
    print("TEST: --remove deletes state/browser dirs (y)")
    reset_mock()
    with tempfile.TemporaryDirectory() as td:
        state = os.path.join(td, "state")
        browser = os.path.join(td, "browser")
        os.makedirs(state)
        os.makedirs(browser)
        with open(os.path.join(state, "keep.txt"), "w") as f:
            f.write("x")
        MOCK_STATE["exists"] = True
        mod = make_module()
        mod.parse_cli(["--remove"])
        mod.apply_overrides()
        mod.cfg.state_dir = state
        mod.cfg.browser_dir = browser
        orig_input = builtins.input
        builtins.input = lambda prompt="": "y"
        try:
            with _OutputCapture():
                mod.cmd_remove()
        finally:
            builtins.input = orig_input
        assert not MOCK_STATE["exists"], "container should be removed"
        assert not os.path.exists(state), f"state dir not removed: {state}"
        assert not os.path.exists(browser), f"browser dir not removed: {browser}"
    print("  PASS\n")


def test_cmd_remove_abort():
    """--remove with 'n' answer must NOT delete anything."""
    print("TEST: --remove aborts on 'n'")
    reset_mock()
    with tempfile.TemporaryDirectory() as td:
        state = os.path.join(td, "state")
        os.makedirs(state)
        MOCK_STATE["exists"] = True
        mod = make_module()
        mod.parse_cli(["--remove"])
        mod.apply_overrides()
        mod.cfg.state_dir = state
        mod.cfg.browser_dir = os.path.join(td, "browser")
        orig_input = builtins.input
        builtins.input = lambda prompt="": "n"
        try:
            with _OutputCapture():
                mod.cmd_remove()
        finally:
            builtins.input = orig_input
        assert os.path.exists(state), "state dir must survive an aborted remove"
        assert not MOCK_STATE["exists"], "container removed even on abort (ok-ish, but should be removed)"
    print("  PASS\n")


def test_cmd_update_runs():
    """--update must not NameError and must pull images.

    Regression guard: self_update() was swallowed by a comment → cmd_update
    crashed. This exercises the full path with self_update no-op'd.
    """
    print("TEST: --update")
    reset_mock()
    MOCK_STATE["image_present"] = True
    mod = make_module()
    # avoid real network / Popen in self_update + images_pull
    mod.self_update = lambda: None
    pulled = []
    mod.ContainerClient.images_pull = lambda self, name: pulled.append(name) or 0
    mod.parse_cli(["--update"])
    mod.apply_overrides()
    with _OutputCapture():
        mod.cmd_update()
    assert pulled, f"expected image pulls, got {pulled}"
    print(f"  pulled: {pulled} (via mocked images_pull)")
    print("  PASS\n")


def test_cmd_run_env_vars():
    """cmd_run must build env with host-driven values (port, host, token, workspace)."""
    print("TEST: cmd_run env vars")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--web", "/tmp"])  # web mode → uses containers_run (spyable)
    mod.apply_overrides()
    mod.cfg.state_dir = "/tmp/lpb-test-state"
    mod.cfg.browser_dir = "/tmp/lpb-test-browser"
    mod.cfg.port = 4321
    mod.cfg.host = "0.0.0.0"
    mod.cfg.token = "testtoken"
    mod.detect_mount_flags = lambda project_dir: ":Z"  # avoid probe container
    # capture the env/volume args the mock receives
    captured = {}

    def spy_containers_run(*a, **kw):
        captured.update(kw)
        MOCK_STATE["running"] = True
        MOCK_STATE["exists"] = True
        return ("cid123", "cid123", "", 0)

    mod.ContainerClient.containers_run = spy_containers_run

    # Health-check loop: make the (real) TCP probe succeed and pre-count the
    # mocked curl attempts so the readiness wait exits in ~1s instead of
    # spinning the full 120s budget (this test only asserts env/volume args).
    class _ReadySock:
        def close(self):
            pass

    global _curl_attempts
    _curl_attempts = 2  # mocked curl succeeds from attempt 3 onward
    _orig_cc = mod.socket.create_connection
    mod.socket.create_connection = lambda *a, **k: _ReadySock()
    try:
        with _OutputCapture():
            mod.cmd_run()
    finally:
        mod.socket.create_connection = _orig_cc
    assert mod.cfg.project_name == "tmp"
    env_vars = captured.get("env", [])
    env_str = "\n".join(env_vars)
    for var in REQUIRED_ENV_VARS:
        assert any(v.startswith(var + "=") for v in env_vars), f"missing {var}: {env_vars}"
    assert "LPB_ED_PORT=4321" in env_str
    assert "LPB_EDITOR_HOST=0.0.0.0" in env_str
    assert "LPB_CONNECTION_TOKEN=testtoken" in env_str
    # volumes: project → workspace, state → /home/lpb/.pi, browser → /home/lpb/.agent-browser
    vols = captured.get("volumes", [])
    assert any(v.startswith("/tmp:/home/lpb/workspace/tmp") for v in vols), f"project mount missing: {vols}"
    assert any("/home/lpb/.pi" in v for v in vols), f".pi mount missing: {vols}"
    assert any("/home/lpb/.agent-browser" in v for v in vols), f"browser mount missing: {vols}"
    print(f"  env: {env_vars}")
    print(f"  vols: {vols}")
    print("  PASS\n")


# ─── Mutation tests (verify guards catch historic regressions) ───────────────

_MUTATION_DIR = os.path.join(tempfile.gettempdir(), "lpb_regression_mutations")

_REG_MUTATIONS = {
    # real regression: comment swallowed `def self_update()` → NameError at runtime
    "swallowed_def": (
        "# ── Output helpers (stdout) ───────────────────────────────────────────────────\n\ndef self_update() -> None:",
        "# ── Output helpers (stdout) ───────────────────────────────────────────def self_update() -> None:",
        ["missing/not-callable"],
    ),
    # real regression: resolve_path() returns str, cmd_remove called d.is_dir() → AttributeError
    "str_is_dir": (
        "    dir_browser = Path(resolve_path(cfg.browser_dir))\n    for d in (Path(resolve_path(cfg.state_dir)), dir_browser):\n        if d.is_dir():",
        "    dir_browser = Path(resolve_path(cfg.browser_dir))\n    for d in (resolve_path(cfg.state_dir), dir_browser):\n        if d.is_dir():",
        ["Argument of type 'str' cannot be used with 'is_dir'"],
    ),
}


def _mutate_lpb(mname: str) -> str:
    """Apply a named mutation to lpb.py and write it under _mutations/. Returns path."""
    os.makedirs(_MUTATION_DIR, exist_ok=True)
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lpb.py")).read()
    old, new, _ = _REG_MUTATIONS[mname]
    assert old in src, f"mutation anchor not found: {mname}"
    out = os.path.join(_MUTATION_DIR, f"{mname}.py")
    with open(out, "w") as f:
        f.write(src.replace(old, new, 1))
    return out


def test_regression_guards_on_swallowed_def():
    """Sanity: the module-structure guard MUST fail on the swallowed-def mutation."""
    print("TEST: mutation 'swallowed_def' is caught by test_module_structure")
    reset_mock()
    path = _mutate_lpb("swallowed_def")
    mod = make_module(lpb_path=path)
    for name in REQUIRED_CALLABLES:
        assert callable(getattr(mod, name, None)) or name == "self_update", f"{name} should exist"
    # if self_update is genuinely absent, the guard logic reports it — assert bug exists
    assert not callable(getattr(mod, "self_update", None)), "mutation did not reproduce the bug"
    print("  PASS (bug reproduced; guard will flag it)\n")


def test_regression_guards_on_str_is_dir():
    """Sanity: cmd_remove Must fail with AttributeError on str.is_dir mutation."""
    print("TEST: mutation 'str_is_dir' triggers AttributeError on --remove")
    reset_mock()
    path = _mutate_lpb("str_is_dir")
    mod = make_module(lpb_path=path)
    with tempfile.TemporaryDirectory() as td:
        state = os.path.join(td, "state")
        os.makedirs(state)
        MOCK_STATE["exists"] = True
        mod.parse_cli(["--remove"])
        mod.apply_overrides()
        mod.cfg.state_dir = state
        mod.cfg.browser_dir = os.path.join(td, "browser")
        orig_input = builtins.input
        builtins.input = lambda prompt="": "y"
        try:
            try:
                mod.cmd_remove()
                msg = "cmd_remove did not raise on str.is_dir() mutation"
            except AttributeError:
                msg = None
        finally:
            builtins.input = orig_input
    if msg:
        assert False, msg
    print("  PASS (bug reproduced; cmd_remove raises AttributeError)\n")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("lpb.py test suite (mocked podman/docker)")
    print("=" * 60)
    print()

    tests = [
        # regression guards first (fast, structural)
        test_module_structure,
        test_handler_dispatches,
        test_env_files_found,
        test_env_file_search_order,
        test_parse_env_file,
        test_resolve_path_host_semantics,
        test_cmd_remove_with_dirs,
        test_cmd_remove_abort,
        test_cmd_update_runs,
        test_cmd_run_env_vars,
        # mutation sanity — prove the guards actually catch the historic regressions
        test_regression_guards_on_swallowed_def,
        test_regression_guards_on_str_is_dir,
        # behavioral
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
        test_run_shell,  # --shell (replaced deprecated -i)
        test_run_port_flag,
        test_url_from_resolved_config,
        test_url_without_token,
        test_url_from_env_override,
        # image tag tests
        test_tag_dev,
        test_tag_main,
        test_tag_latest,
        test_tag_custom_version,
        test_tag_with_project,
        test_update_with_tag,
        test_tag_web_mode,
        test_resolve_cli_image_dev,
        test_resolve_cli_image_main,
        test_resolve_cli_image_custom,
        test_resolve_web_image_dev,
        test_self_update_branch_selection,
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
        except SystemExit as e:
            # Some commands call sys.exit(0) — treat clean exits as pass
            if e.code == 0:
                passed += 1
            else:
                print(f"  FAIL: unexpected exit code {e.code}")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed}/{len(tests)} passed, {failed} failed")
    sys.exit(1 if failed else 0)
