#!/usr/bin/env python3
"""SSH mode tests: key auto-detection from ~/.ssh profile, explicit key
(literal or path), password auth (--ssh-password), env var passthrough.

Part of the lpb.py family (run via test_lpb.py or directly)."""
from __future__ import annotations

import os
import shutil

from testharness import make_module, reset_mock


def _clear_ssh():
    shutil.rmtree(os.path.join(os.environ["HOME"], ".ssh"), ignore_errors=True)


def _ssh_dir():
    d = os.path.join(os.environ["HOME"], ".ssh")
    os.makedirs(d, exist_ok=True)
    return d


def _write_key(name: str) -> str:
    d = _ssh_dir()
    key = f"ssh-ed25519 AAAAC3-{name} {name}@host"
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(key + "\n")
    return path


def test_ssh_explicit_key_literal():
    print("TEST: --ssh <literal key>")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh", "ssh-ed25519 AAAA literal@host"])
    mod.apply_overrides()
    assert mod.cfg.ssh_mode and mod.cfg.shell_mode
    assert mod.cfg.ssh_pubkey == "ssh-ed25519 AAAA literal@host"
    assert mod.cfg.ssh_password == ""
    print("  PASS\n")


def test_ssh_explicit_key_path():
    print("TEST: --ssh <path to .pub>")
    reset_mock()
    _clear_ssh()
    mod = make_module()
    path = _write_key("id_ed25519.pub")
    mod.parse_cli(["--ssh", path])
    mod.apply_overrides()
    assert mod.cfg.ssh_pubkey == f"ssh-ed25519 AAAAC3-id_ed25519.pub id_ed25519.pub@host"
    print("  PASS\n")


def test_ssh_no_key_no_profile_keys():
    print("TEST: --ssh with no key and empty ~/.ssh → error")
    reset_mock()
    _clear_ssh()
    mod = make_module()
    try:
        mod.parse_cli(["--ssh"])
        raise AssertionError("expected DevstackError")
    except mod.DevstackError:
        pass
    print("  PASS\n")


def test_ssh_auto_single_key():
    print("TEST: --ssh with one profile key → auto-used (non-interactive)")
    reset_mock()
    _clear_ssh()
    mod = make_module()
    _write_key("id_ed25519.pub")
    mod.parse_cli(["--ssh"])
    mod.apply_overrides()
    assert mod.cfg.ssh_pubkey == "ssh-ed25519 AAAAC3-id_ed25519.pub id_ed25519.pub@host"
    print("  PASS\n")


def test_ssh_auto_multiple_keys_noninteractive():
    print("TEST: --ssh with multiple profile keys, no TTY → error")
    reset_mock()
    _clear_ssh()
    mod = make_module()
    _write_key("a.pub")
    _write_key("b.pub")
    try:
        mod.parse_cli(["--ssh"])
        raise AssertionError("expected DevstackError")
    except mod.DevstackError:
        pass
    print("  PASS\n")


def test_ssh_password_flag_random():
    print("TEST: --ssh --ssh-password → random password, no key needed")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh", "--ssh-password"])
    mod.apply_overrides()
    assert mod.cfg.ssh_mode and mod.cfg.shell_mode
    assert mod.cfg.ssh_pubkey == ""
    assert len(mod.cfg.ssh_password) >= 12
    print("  PASS\n")


def test_ssh_password_value():
    print("TEST: --ssh --ssh-password <pw> → user-chosen password")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh", "--ssh-password", "hunter2"])
    mod.apply_overrides()
    assert mod.cfg.ssh_password == "hunter2"
    print("  PASS\n")


def test_ssh_password_alone_enables_ssh_mode():
    print("TEST: --ssh-password without --ssh → ssh mode enabled")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh-password"])
    mod.apply_overrides()
    assert mod.cfg.ssh_mode and mod.cfg.shell_mode
    assert len(mod.cfg.ssh_password) >= 12
    print("  PASS\n")


def test_ssh_key_and_password_combine():
    print("TEST: --ssh <key> --ssh-password <pw> → both")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh", "ssh-ed25519 AAAA k@h", "--ssh-password", "pw1"])
    mod.apply_overrides()
    assert mod.cfg.ssh_pubkey == "ssh-ed25519 AAAA k@h"
    assert mod.cfg.ssh_password == "pw1"
    print("  PASS\n")


def test_ssh_env_vars_passthrough():
    print("TEST: LPB_SSH_PUBKEY / LPB_SSH_PASSWORD / LPB_SSH_PORT env vars")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh", "ssh-ed25519 AAAA k@h", "--ssh-password", "pw1"])
    mod.apply_overrides()
    env = mod._build_run_env("/home/lpb/workspace")
    joined = "\n".join(env)
    assert "LPB_SSH_PUBKEY=ssh-ed25519 AAAA k@h" in joined
    assert "LPB_SSH_PASSWORD=pw1" in joined
    assert any(v.startswith("LPB_SSH_PORT=") for v in env)
    print("  PASS\n")


def test_ssh_password_only_env_vars():
    print("TEST: password-only SSH → no LPB_SSH_PUBKEY, port present")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--ssh-password"])
    mod.apply_overrides()
    env = mod._build_run_env("/home/lpb/workspace")
    assert not any(v.startswith("LPB_SSH_PUBKEY=") for v in env)
    assert any(v.startswith("LPB_SSH_PASSWORD=") for v in env)
    assert any(v.startswith("LPB_SSH_PORT=") for v in env)
    print("  PASS\n")


TESTS = [
    test_ssh_explicit_key_literal,
    test_ssh_explicit_key_path,
    test_ssh_no_key_no_profile_keys,
    test_ssh_auto_single_key,
    test_ssh_auto_multiple_keys_noninteractive,
    test_ssh_password_flag_random,
    test_ssh_password_value,
    test_ssh_password_alone_enables_ssh_mode,
    test_ssh_key_and_password_combine,
    test_ssh_env_vars_passthrough,
    test_ssh_password_only_env_vars,
]


def main() -> int:
    from testharness import run_lpb_suite
    return run_lpb_suite("lpb.py SSH tests", TESTS)


if __name__ == "__main__":
    raise SystemExit(main())
