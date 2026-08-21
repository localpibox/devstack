#!/usr/bin/env python3
"""localpibox stack workspace-sync tests (via the _stack_lib shim):
detached-head checkout, clone-missing, dirty skip, wrong branch, missing
config, main pipeline."""
from __future__ import annotations

from testharness import run_lpbx_suite, _bare_remote, _push_branch, _quiet_console, log_mod

import os
import io
import subprocess
from unittest import mock

from localpibox import _stack_lib as sl
from localpibox.stack import workspace as ws_mod


def _workspace_patch(tmpdir, repos, config_branch="dev", config_repo=True):
    """Point lpb-config workspace constants at *tmpdir* (context manager).

    Installs a clean config repo on *config_branch* at the agent dir unless
    config_repo is False. Mirrors the real layout: the agent dir is a git
    repo whose worktree contains the extension clones under git/ (ignored).
    """
    agent = tmpdir / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    if config_repo:
        cfg_remote, _ = _bare_remote(tmpdir, "config", config_branch)
        subprocess.run(["git", "-C", str(agent), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(agent), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(agent), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(agent), "remote", "add", "origin", str(cfg_remote)], check=True)
        subprocess.run(["git", "-C", str(agent), "fetch", "-q", "origin", config_branch], check=True)
        subprocess.run(["git", "-C", str(agent), "checkout", "-q", "-b", config_branch, "FETCH_HEAD"], check=True)
        (agent / ".gitignore").write_text("git/\n")
        subprocess.run(["git", "-C", str(agent), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(agent), "commit", "-qm", "gitignore"], check=True)
        subprocess.run(["git", "-C", str(agent), "push", "-q", "origin", config_branch], check=True)
    return mock.patch.multiple(
        ws_mod,
        WORKSPACE_REPOS=repos,
        WORKSPACE_ROOT=tmpdir / "workspace",
        AGENT_GIT=agent / "git" / "github.com" / "lpb-stack",
        DEFAULT_AGENT_DIR=str(agent),
    )


def _branch(p):
    return subprocess.run(
        ["git", "-C", str(p), "branch", "--show-current"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_lpb_config_sync_detached_head(tmpdir):
    """Clone detached at a tag (pi's pinned-tag checkout) → ends on branch @ tip."""
    remote, src = _bare_remote(tmpdir, "repo-a", "dev")
    ag = tmpdir / "agent" / "git" / "github.com" / "lpb-stack"
    clone = ag / "repo-a"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "0.0.1"], check=True)
    _push_branch(src, "dev")
    with _workspace_patch(tmpdir, [("repo-a", True, True, "dev", "main")]):
        code = sl.cmd_workspace_sync("dev", _quiet_console())
    ws = tmpdir / "workspace"
    assert code == 0
    assert (ws / "repo-a").is_symlink()
    assert (ws / "repo-a").resolve() == clone.resolve()
    assert _branch(clone) == "dev"
    assert (clone / "f").read_text() == "two"  # fast-forwarded


def test_lpb_config_sync_clones_missing(tmpdir):
    """Missing extension clone + missing real repo → both cloned and linked."""
    repos = [("repo-a", True, True, "dev", "main"), ("repo-b", False, False, "dev", "main")]
    _bare_remote(tmpdir, "repo-a", "dev")
    _bare_remote(tmpdir, "repo-b", "dev")
    with mock.patch.dict(os.environ, {"LPB_STACK_REMOTE_BASE": str(tmpdir / "remotes")}), \
         _workspace_patch(tmpdir, repos):
        code = sl.cmd_workspace_sync("dev", _quiet_console())
    ws = tmpdir / "workspace"
    ag = tmpdir / "agent" / "git" / "github.com" / "lpb-stack"
    assert code == 0
    assert (ag / "repo-a" / ".git").exists()
    assert (ws / "repo-a").is_symlink()
    assert (ws / "repo-b" / ".git").exists()  # real clone in workspace
    assert _branch(ws / "repo-b") == "dev"


def test_lpb_config_sync_dirty_skipped(tmpdir):
    """Dirty worktree → left untouched, reported, non-zero exit."""
    remote, src = _bare_remote(tmpdir, "repo-a", "dev")
    clone = tmpdir / "agent" / "git" / "github.com" / "lpb-stack" / "repo-a"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    (clone / "f").write_text("local edit")
    _push_branch(src, "dev")
    out, err = io.StringIO(), io.StringIO()
    with _workspace_patch(tmpdir, [("repo-a", True, True, "dev", "main")]):
        cons = log_mod.Console(color=False, out=out, err=err)
        code = sl.cmd_workspace_sync("dev", cons)
    assert code == 1
    assert _branch(clone) == "dev"
    assert (clone / "f").read_text() == "local edit"  # untouched
    assert "uncommitted changes" in (out.getvalue() + err.getvalue())


def test_lpb_config_sync_wrong_branch(tmpdir):
    """Clean repo on a feature branch → switched to pipeline branch @ tip."""
    remote, src = _bare_remote(tmpdir, "repo-a", "dev")
    subprocess.run(["git", "-C", str(src), "checkout", "-q", "-b", "feature"], check=True)
    subprocess.run(["git", "-C", str(src), "push", "-q", "origin", "feature"], check=True)
    clone = tmpdir / "agent" / "git" / "github.com" / "lpb-stack" / "repo-a"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "feature"], check=True)
    _push_branch(src, "dev")
    with _workspace_patch(tmpdir, [("repo-a", True, True, "dev", "main")]):
        code = sl.cmd_workspace_sync("dev", _quiet_console())
    assert code == 0
    assert _branch(clone) == "dev"
    assert (clone / "f").read_text() == "two"


def test_lpb_config_sync_missing_config(tmpdir):
    """No config repo at agent dir → warning + non-zero exit."""
    remote, src = _bare_remote(tmpdir, "repo-a", "dev")
    clone = tmpdir / "agent" / "git" / "github.com" / "lpb-stack" / "repo-a"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    out, err = io.StringIO(), io.StringIO()
    with _workspace_patch(tmpdir, [("repo-a", True, True, "dev", "main")], config_repo=False):
        cons = log_mod.Console(color=False, out=out, err=err)
        code = sl.cmd_workspace_sync("dev", cons)
    assert code == 1
    assert "config" in (out.getvalue() + err.getvalue())


def test_lpb_config_sync_main_pipeline(tmpdir):
    """main pipeline → main branches selected for repo + config."""
    remote, src = _bare_remote(tmpdir, "repo-a", "dev")
    subprocess.run(["git", "-C", str(src), "checkout", "-q", "-b", "main"], check=True)
    (src / "f").write_text("stable")
    subprocess.run(["git", "-C", str(src), "commit", "-qam", "stable"], check=True)
    subprocess.run(["git", "-C", str(src), "push", "-q", "origin", "main"], check=True)
    clone = tmpdir / "agent" / "git" / "github.com" / "lpb-stack" / "repo-a"
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(remote), str(clone)], check=True)
    with _workspace_patch(tmpdir, [("repo-a", True, True, "dev", "main")], config_branch="main"):
        code = sl.cmd_workspace_sync("main", _quiet_console())
    assert code == 0
    assert _branch(clone) == "main"
    assert (clone / "f").read_text() == "stable"


def main() -> int:
    return run_lpbx_suite("lpb-config workspace sync tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
