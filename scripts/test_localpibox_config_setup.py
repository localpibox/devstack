#!/usr/bin/env python3
"""scripts/lpb-config setup (first-run wizard) tests: auth.json shape,
model selection + settings.json, memory prefill, idempotency,
unreachable-server failure, interactive flow."""
from __future__ import annotations

import builtins
import json
import os
import sys

from testharness import run_lpbx_suite, _quiet_console, _load_script, SCRIPTS_DIR

import io
from localpibox import log as log_mod

lc = _load_script('lpb_config', SCRIPTS_DIR / 'lpb-config')


def _capture_console():
    out, err = io.StringIO(), io.StringIO()
    cons = log_mod.Console(color=False, out=out, err=err)
    return cons, lambda: out.getvalue() + err.getvalue()


MODELS = {"data": [
    {"id": "Qwen3.8-27B-GGUF", "name": "Qwen 3.8 27B", "max_context_window": 262144},
    {"id": "qwen3.5-9b-FLM", "name": "Qwen 3.5 9B", "max_context_window": 32768},
]}
HEALTH = {"all_models_loaded": [{"model_name": "qwen3.5-9b-FLM"}]}


def _fake_http_get(url, timeout=8.0):
    if url.endswith("/api/v1/models"):
        return MODELS
    if url.endswith("/api/v1/health"):
        return HEALTH
    raise AssertionError(f"unexpected url {url}")


def _make_agent_dir(tmpdir):
    agent = tmpdir / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(json.dumps({"theme": "dark"}))
    (agent / "lpb-memory-config.json.template").write_text(json.dumps(
        {"reviewTransport": "subprocess", "memoryMode": "legacy-inject"}))
    return agent


def _env_setup():
    os.environ["LEMONADE_BASE_URL"] = "http://192.168.0.13:13305/v1"
    os.environ["LEMONADE_API_KEY"] = "lemony"


def _env_teardown():
    os.environ.pop("LEMONADE_BASE_URL", None)
    os.environ.pop("LEMONADE_API_KEY", None)


def test_bare_base_url_normalization():
    assert lc._bare_base_url("http://127.0.0.1:13305/v1") == "http://127.0.0.1:13305"
    assert lc._bare_base_url("http://192.168.0.13:13305/api/v1/") == "http://192.168.0.13:13305"
    assert lc._bare_base_url("192.168.0.13:8000") == "http://192.168.0.13:8000"
    assert lc._bare_base_url("") == ""
    print("  PASS\n")


def test_setup_noninteractive(tmpdir):
    agent = _make_agent_dir(tmpdir)
    orig = lc._http_get_json
    lc._http_get_json = _fake_http_get
    _env_setup()
    try:
        rc = lc.cmd_setup(agent_dir=agent, non_interactive=True,
                          cons=_quiet_console())
    finally:
        lc._http_get_json = orig
        _env_teardown()
    assert rc == 0
    auth = json.loads((agent / "auth.json").read_text())
    entry = auth["lemonade"]
    assert entry["type"] == "oauth"
    assert entry["access"] == "lemony"
    assert isinstance(entry["expires"], int) and entry["expires"] > 0
    refresh = json.loads(entry["refresh"])
    assert refresh["baseUrl"] == "http://192.168.0.13:13305"  # /v1 stripped
    assert refresh["apiKey"] == "lemony"
    assert refresh["serverName"] == "192.168.0.13"
    settings = json.loads((agent / "settings.json").read_text())
    assert settings["defaultProvider"] == "lemonade"
    assert settings["defaultModel"] == "qwen3.5-9b-FLM"  # loaded model wins
    mem = json.loads((agent / "lpb-memory-config.json").read_text())
    assert mem["llmModelOverride"] == "qwen3.5-9b-FLM"
    assert mem["llmThinkingOverride"] == "low"
    print("  PASS\n")


def test_setup_idempotent(tmpdir):
    agent = _make_agent_dir(tmpdir)
    orig = lc._http_get_json
    lc._http_get_json = _fake_http_get
    _env_setup()
    try:
        assert lc.cmd_setup(agent_dir=agent, non_interactive=True,
                            cons=_quiet_console()) == 0
        auth_before = (agent / "auth.json").read_text()
    finally:
        lc._http_get_json = orig
        _env_teardown()
    # Second run: creds exist → no-op, no network (no fake http in place)
    cons, text = _capture_console()
    rc = lc.cmd_setup(agent_dir=agent, non_interactive=True, cons=cons)
    assert rc == 0
    assert "already configured" in text()
    assert (agent / "auth.json").read_text() == auth_before
    print("  PASS\n")


def test_setup_reconfigure(tmpdir):
    agent = _make_agent_dir(tmpdir)
    orig = lc._http_get_json
    lc._http_get_json = _fake_http_get
    _env_setup()
    try:
        assert lc.cmd_setup(agent_dir=agent, non_interactive=True,
                            cons=_quiet_console()) == 0
        assert lc.cmd_setup(agent_dir=agent, non_interactive=True,
                            reconfigure=True, cons=_quiet_console()) == 0
    finally:
        lc._http_get_json = orig
        _env_teardown()
    auth = json.loads((agent / "auth.json").read_text())
    assert auth["lemonade"]["access"] == "lemony"
    print("  PASS\n")


def test_setup_noninteractive_unreachable(tmpdir):
    agent = _make_agent_dir(tmpdir)

    def boom(url, timeout=8.0):
        raise OSError("connection refused")

    orig = lc._http_get_json
    lc._http_get_json = boom
    os.environ.pop("LEMONADE_BASE_URL", None)
    try:
        rc = lc.cmd_setup(agent_dir=agent, non_interactive=True,
                          cons=_quiet_console())
    finally:
        lc._http_get_json = orig
        os.environ.pop("LEMONADE_API_KEY", None)
    assert rc == 1
    assert not (agent / "auth.json").exists()  # nothing written on failure
    print("  PASS\n")


def test_setup_interactive_pick(tmpdir):
    agent = _make_agent_dir(tmpdir)
    orig_http = lc._http_get_json
    lc._http_get_json = _fake_http_get
    _env_setup()
    # Answers: URL (accept), key, model pick 1, then memory wizard
    # (mode, transport, model, limit, limit, limit)
    answers = iter(["", "mykey", "1", "", "", "", "", "", ""])
    orig_input = builtins.input
    orig_isatty = sys.stdin.isatty
    builtins.input = lambda prompt="": next(answers)
    sys.stdin.isatty = lambda: True
    try:
        rc = lc.cmd_setup(agent_dir=agent, cons=_quiet_console())
    finally:
        sys.stdin.isatty = orig_isatty
        builtins.input = orig_input
        lc._http_get_json = orig_http
        _env_teardown()
    assert rc == 0
    refresh = json.loads(json.loads((agent / "auth.json").read_text())["lemonade"]["refresh"])
    assert refresh["apiKey"] == "mykey"
    settings = json.loads((agent / "settings.json").read_text())
    assert settings["defaultModel"] == "Qwen3.8-27B-GGUF"  # user picked 1
    mem = json.loads((agent / "lpb-memory-config.json").read_text())
    assert mem["llmModelOverride"] == "Qwen3.8-27B-GGUF"  # prefill default
    print("  PASS\n")


def test_setup_no_settings_json_warns(tmpdir):
    agent = tmpdir / "agent"
    agent.mkdir()
    (agent / "lpb-memory-config.json.template").write_text(json.dumps(
        {"reviewTransport": "subprocess"}))
    orig = lc._http_get_json
    lc._http_get_json = _fake_http_get
    _env_setup()
    try:
        cons, text = _capture_console()
        rc = lc.cmd_setup(agent_dir=agent, non_interactive=True, cons=cons)
    finally:
        lc._http_get_json = orig
        _env_teardown()
    assert rc == 0
    assert "settings.json not found" in text()
    assert (agent / "auth.json").exists()  # provider still configured
    print("  PASS\n")


def test_memory_setup_noninteractive_default_model(tmpdir):
    agent = _make_agent_dir(tmpdir)
    rc = lc.cmd_memory_setup(agent_dir=agent, non_interactive=True,
                             default_model="qwen3.5-9b-FLM",
                             cons=_quiet_console())
    assert rc == 0
    mem = json.loads((agent / "lpb-memory-config.json").read_text())
    assert mem["llmModelOverride"] == "qwen3.5-9b-FLM"
    print("  PASS\n")


def main() -> int:
    return run_lpbx_suite("lpb-config setup (first-run wizard) tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
