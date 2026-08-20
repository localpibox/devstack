#!/usr/bin/env python3
"""support/lpb-config tests: legacy layout migration, update
(clone/fast-forward/refuse-dirty), reset (force/abort), status states,
merge."""
from __future__ import annotations

from testharness import run_lpbx_suite, _quiet_console, log_mod, _load_script, SUPPORT_DIR

import io
import subprocess

lc = _load_script('lpb_config', SUPPORT_DIR / 'lpb-config')

# NOTE: These tests are stubs for lpb-config features (repo listing,
# mirror management) that are not yet implemented. They are skipped
# until the underlying functions exist.
# ═══════════════════════════════════════════════════════════════════════════



def _setup_git_remote(tmpdir):
    """Create a bare remote + work clone with one commit on 'main'."""
    remote = tmpdir / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    work = tmpdir / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(work), "branch", "-M", "main"], check=True)
    (work / "f").write_text("one")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "one"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"], check=True)
    return remote


def _push_commit(work, msg, content):
    (work / "f").write_text(content)
    subprocess.run(["git", "-C", str(work), "commit", "-qam", msg], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"], check=True)




def test_lpb_config_migrate_legacy_layout(tmpdir):
    pi_root = tmpdir / ".pi"
    pi_root.mkdir()
    (pi_root / ".git").mkdir()
    (pi_root / "auth.json").write_text("{}")
    (pi_root / ".initialized").touch()
    (pi_root / "agent").mkdir()
    cons = _quiet_console()
    lc.migrate_legacy_layout(pi_root, tmpdir / "agent_dir", cons)
    assert (tmpdir / "agent_dir" / "auth.json").exists()
    assert (pi_root / ".initialized").exists()       # marker preserved
    assert (pi_root / "agent").exists()              # subdir preserved
    assert not (pi_root / "auth.json").exists()


def test_lpb_config_migrate_noop_when_already_migrated(tmpdir):
    pi_root = tmpdir / ".pi"
    pi_root.mkdir()
    agent = tmpdir / "agent"
    agent.mkdir()
    (agent / ".git").mkdir()
    cons = _quiet_console()
    lc.migrate_legacy_layout(pi_root, agent, cons)  # must not raise
    assert True


def test_lpb_config_update_clones(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    cons = _quiet_console()
    code = lc.cmd_update(agent, str(remote), "main", cons)
    assert code == 0
    assert (agent / "f").exists()


def test_lpb_config_update_fast_forward(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    lc.cmd_update(agent, str(remote), "main", _quiet_console())
    _push_commit(tmpdir / "work", "two", "two")
    cons = _quiet_console()
    assert lc.cmd_update(agent, str(remote), "main", cons) == 0
    assert (agent / "f").read_text() == "two"


def test_lpb_config_update_refuses_when_dirty(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    lc.cmd_update(agent, str(remote), "main", _quiet_console())
    _push_commit(tmpdir / "work", "two", "two")
    (agent / "local").write_text("keep")  # untracked = dirty
    cons = _quiet_console()
    assert lc.cmd_update(agent, str(remote), "main", cons) == 1
    assert (agent / "local").exists()


def test_lpb_config_reset_force(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    lc.cmd_update(agent, str(remote), "main", _quiet_console())
    _push_commit(tmpdir / "work", "two", "two")
    (agent / "junk").write_text("x")
    cons = _quiet_console()
    assert lc.cmd_reset(agent, str(remote), "main", cons, force=True) == 0
    assert not (agent / "junk").exists()
    assert (agent / "f").read_text() == "two"


def test_lpb_config_reset_abort_without_confirmation(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    lc.cmd_update(agent, str(remote), "main", _quiet_console())
    (agent / "junk").write_text("x")
    cons = _quiet_console()
    assert lc.cmd_reset(agent, str(remote), "main", cons, force=False, inp=io.StringIO("n\n")) == 0
    assert (agent / "junk").exists()


def test_lpb_config_status_states(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    lc.cmd_update(agent, str(remote), "main", _quiet_console())
    out, err = io.StringIO(), io.StringIO()
    cons = log_mod.Console(color=False, out=out, err=err)
    assert lc.cmd_status(agent, str(remote), "main", cons) == 0
    text = out.getvalue() + err.getvalue()
    assert "Current:" in text and "Remote:" in text and "clean" in text
    # no repo yet
    out2, err2 = io.StringIO(), io.StringIO()
    cons2 = log_mod.Console(color=False, out=out2, err=err2)
    assert lc.cmd_status(tmpdir / "nope", str(remote), "main", cons2) == 0
    assert "No config repo" in (out2.getvalue() + err2.getvalue())


def test_lpb_config_merge_uptodate(tmpdir):
    remote = _setup_git_remote(tmpdir)
    agent = tmpdir / "agent"
    lc.cmd_update(agent, str(remote), "main", _quiet_console())
    cons = _quiet_console()
    assert lc.cmd_merge(agent, str(remote), "main", cons) == 0
    # merge when no repo -> error
    assert lc.cmd_merge(tmpdir / "nope", str(remote), "main", _quiet_console()) == 1


def main() -> int:
    return run_lpbx_suite("lpb-config tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
