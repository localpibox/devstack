#!/usr/bin/env python3
"""support/install-openspec tests: skip when installed, install
retries, init new/existing, verify, target resolution."""
from __future__ import annotations

from testharness import run_lpbx_suite, _quiet_console

from unittest import mock
import importlib

iospec = importlib.import_module('install-openspec')


def test_openspec_skips_when_installed(tmpdir):
    cons = _quiet_console()
    with mock.patch.object(iospec, "which", return_value="/bin/openspec"), \
         mock.patch.object(iospec, "run_cmd", return_value=("1.2.3", "", 0)):
        assert iospec.install_openspec(cons) == 0
        assert "already installed" in cons.out.getvalue()


def test_openspec_install_retries_then_fails(tmpdir):
    cons = _quiet_console()
    with mock.patch.object(iospec, "which", return_value=None), \
         mock.patch.object(iospec, "run_cmd", return_value=("", "npm err", 1)), \
         mock.patch.object(iospec.time, "sleep", return_value=None):
        assert iospec.install_openspec(cons) == 1
        assert "3 attempts" in cons.err.getvalue()


def test_openspec_init_new(tmpdir):
    target = tmpdir / "proj"
    target.mkdir()
    cons = _quiet_console()
    with mock.patch.object(iospec, "run_cmd", return_value=("", "", 0)) as m:
        assert iospec.init_openspec(target, cons) == 0
    assert m.call_args.args[0] == ["openspec", "init", "--tools", "pi"]


def test_openspec_init_existing_runs_update(tmpdir):
    target = tmpdir / "proj"
    (target / "openspec").mkdir(parents=True)
    cons = _quiet_console()
    with mock.patch.object(iospec, "run_cmd", return_value=("", "", 0)) as m:
        assert iospec.init_openspec(target, cons) == 0
    assert m.call_args.args[0] == ["openspec", "update"]


def test_openspec_verify(tmpdir):
    target = tmpdir / "proj"
    (target / "openspec").mkdir(parents=True)
    (target / "openspec" / "config.yaml").write_text("x")
    (target / ".pi" / "prompts").mkdir(parents=True)
    (target / ".pi" / "prompts" / "opsx-propose.md").write_text("x")
    (target / ".pi" / "prompts" / "opsx-apply.md").write_text("x")
    (target / ".pi" / "skills" / "openspec-foo").mkdir(parents=True)
    cons = _quiet_console()
    assert iospec.verify_installation(target, cons) == 0
    assert "2 command files" in cons.out.getvalue()


def test_openspec_verify_missing_openspec(tmpdir):
    target = tmpdir / "proj"
    target.mkdir()
    cons = _quiet_console()
    assert iospec.verify_installation(target, cons) == 1
    assert "missing" in cons.err.getvalue()


def test_openspec_resolve_target(tmpdir):
    assert iospec.resolve_target_dir(str(tmpdir)) == tmpdir.resolve()


def main() -> int:
    return run_lpbx_suite("install-openspec tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
