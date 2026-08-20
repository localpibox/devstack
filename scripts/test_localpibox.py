#!/usr/bin/env python3
"""Test harness for the lpb-stack package and the ported shell scripts.

Covers:
  - lpb-stack.env    — parse/expand/layer KEY=VALUE files
  - lpb-stack.log    — leveled, colored output to configurable streams
  - lpb-stack.run    — subprocess helpers, tool discovery, container detection
  - lpb-stack.cli    — prompts, common flags, fatal-error helper
  - lpb-stack._stack_lib — pipeline detection, VERSION bumping, workspace sync
  - support/build.py  — env loading, build-arg mapping, docker command
  - browser-state-cleanup — session pruning (age + count)
  - support/lpb-config — config repo manager (update/reset/status/merge/migrate)
  - support/lpb-devstack — DevOps tool (bump, tag-repos)

Runs with plain Python (no third-party deps), mirroring scripts/test_lpb.py.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util  # noqa: E402
import datetime
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent
DEVSTACK_DIR = SCRIPTS_DIR.parent
SUPPORT_DIR = DEVSTACK_DIR / "support"

for _d in (str(SCRIPTS_DIR), str(SUPPORT_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from localpibox import env as env_mod  # noqa: E402
from localpibox import log as log_mod  # noqa: E402
from localpibox import run as run_mod  # noqa: E402
from localpibox import cli as cli_mod  # noqa: E402
from localpibox import _stack_lib as sl  # noqa: E402
from localpibox.stack import version as ver_mod  # noqa: E402
from localpibox.stack import workspace as ws_mod  # noqa: E402
import build  # noqa: E402
bsc = importlib.import_module('browser-state-cleanup')


def _load_script(name: str, path: Path):
    """Load an (extensionless) script file as a module for testing."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load_script('lpb_config', SUPPORT_DIR / 'lpb-config')
ld = _load_script('lpb_devstack', SUPPORT_DIR / 'lpb-devstack')
validate = importlib.import_module('validate')
ib = importlib.import_module('install-browser')
iospec = importlib.import_module('install-openspec')


# ═══════════════════════════════════════════════════════════════════════════
# lpb-stack.env
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_env_line_basic():
    assert env_mod.parse_env_line("A=b") == ("A", "b")
    assert env_mod.parse_env_line(" A = b ") == ("A", "b")
    assert env_mod.parse_env_line("export A=b") == ("A", "b")
    assert env_mod.parse_env_line("A=b=c") == ("A", "b=c")
    assert env_mod.parse_env_line('A="quoted value"') == ("A", "quoted value")
    assert env_mod.parse_env_line("A='sq'") == ("A", "sq")


def test_parse_env_line_skips():
    assert env_mod.parse_env_line("") == (None, "")
    assert env_mod.parse_env_line("   ") == (None, "")
    assert env_mod.parse_env_line("# comment") == (None, "")
    assert env_mod.parse_env_line("  # indented") == (None, "")
    assert env_mod.parse_env_line("no equals sign") == (None, "")


def test_parse_env_file(tmpdir):
    f = tmpdir / "x.env"
    f.write_text("# c\nA=1\n\nB= two \nexport C='3'\nGARBAGE\nD=with=equals\n")
    parsed = env_mod.parse_env_file(f)
    assert parsed == {"A": "1", "B": "two", "C": "3", "D": "with=equals"}


def test_parse_env_file_missing_is_empty(tmpdir):
    assert env_mod.parse_env_file(tmpdir / "nope") == {}


def test_load_env_chain_layering_and_expansion(tmpdir):
    base = tmpdir / "a.env"
    base.write_text("A=1\nB=2\nHOME_DIR=${HOME}/x\n")
    over = tmpdir / "b.env"
    over.write_text("B=two\nREF=${A}-suffix\nUNSET_REF=${PI_WORKTREE_ID}\n")
    merged = env_mod.load_env_chain([base, over])
    assert merged["A"] == "1"
    assert merged["B"] == "two"           # later file wins
    assert merged["HOME_DIR"] == os.path.expanduser("~") + "/x"  # from environ
    assert merged["REF"] == "1-suffix"    # from earlier layer
    assert merged["UNSET_REF"] == ""      # unset -> empty


def test_expand_refs():
    assert env_mod.expand_refs("${A}-${B}", {"A": "1"}) == "1-"
    assert env_mod.expand_refs("plain") == "plain"


def test_find_env_file(tmpdir):
    (tmpdir / "lpb.stack.env").write_text("X=1\n")
    found = env_mod.find_env_file("lpb.stack.env", tmpdir, tmpdir / "nope")
    assert found == tmpdir / "lpb.stack.env"
    assert env_mod.find_env_file("missing.env", tmpdir) is None


# ═══════════════════════════════════════════════════════════════════════════
# lpb-stack.log
# ═══════════════════════════════════════════════════════════════════════════

def test_log_levels_and_streams():
    out, err = io.StringIO(), io.StringIO()
    c = log_mod.Console(color=False, out=out, err=err, debug_enabled=True)
    c.info("i"); c.done("d"); c.warn("w"); c.error("e"); c.debug("g")
    assert out.getvalue() == "i\nd\n"
    assert err.getvalue() == "w\ne\ng\n"


def test_log_color_and_no_color():
    out, err = io.StringIO(), io.StringIO()
    c = log_mod.Console(color=True, out=out, err=err)
    c.info("hi")
    assert "\033[0;32m" in out.getvalue() and "\033[0m" in out.getvalue()
    c2 = log_mod.Console(color=False, out=out, err=err)
    c2.info("plain")
    assert out.getvalue().endswith("plain\n")


def test_log_debug_gated():
    out, err = io.StringIO(), io.StringIO()
    c = log_mod.Console(color=False, out=out, err=err, debug_enabled=False)
    c.debug("hidden")
    assert err.getvalue() == ""


# ═══════════════════════════════════════════════════════════════════════════
# lpb-stack.run
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# lpb-stack.cli
# ═══════════════════════════════════════════════════════════════════════════

def test_confirm_defaults():
    inp = io.StringIO("\n")
    assert cli_mod.confirm("go?", default=True, inp=inp) is True
    inp = io.StringIO("\n")
    assert cli_mod.confirm("go?", default=False, inp=inp) is False


def test_confirm_answers():
    assert cli_mod.confirm("go?", inp=io.StringIO("y\n")) is True
    assert cli_mod.confirm("go?", inp=io.StringIO("Y\n")) is True
    assert cli_mod.confirm("go?", inp=io.StringIO("yes\n")) is True
    assert cli_mod.confirm("go?", inp=io.StringIO("n\n")) is False
    assert cli_mod.confirm("go?", inp=io.StringIO("no\n")) is False


def test_console_from_args_quiet():
    import argparse
    parser = argparse.ArgumentParser()
    cli_mod.add_common_args(parser)
    args = parser.parse_args(["-q", "--no-color"])
    out, err = io.StringIO(), io.StringIO()
    c = cli_mod.console_from_args(args, base=log_mod.Console(color=False, out=out, err=err))
    c.info("hidden"); c.warn("shown")
    assert out.getvalue() == "" and "shown" in err.getvalue()


def test_die_exits():
    try:
        cli_mod.die("boom", cons=log_mod.Console(color=False, err=io.StringIO()))
        assert False, "die should exit"
    except SystemExit as e:
        assert e.code == 1


# ═══════════════════════════════════════════════════════════════════════════
# support/build.py
# ═══════════════════════════════════════════════════════════════════════════

def _fake_runner(responses):
    """Return a run_cmd-style fn that maps git subcommand -> canned output."""
    def runner(args, timeout=120, cwd=None):
        if args and args[0] == "git":
            sub = args[1]
            out, code = responses.get(sub, ("", 0))
            return out, "", code
        return "", "unexpected cmd", 1
    return runner


def test_build_load_env_success(tmpdir):
    (tmpdir / "lpb.stack.env").write_text(
        "LPB_PI_FORK=https://github.com/lpb-stack/pi.git\n"
        "LPB_PI_REF=lpb\n"
        "LPB_CONFIG_FORK=https://github.com/lpb-stack/config.git\n"
        "LPB_CONFIG_REF=main\n"
        "LPB_IMAGE_CLI=ghcr.io/lpb-stack/devstack:cli\n"
        "LPB_IMAGE_WEB=ghcr.io/lpb-stack/devstack:web\n"
        "LPB_NODE_VERSION=24\n"
        "LPB_VSCODIUM_VERSION=1.126.04524\n"
    )
    (tmpdir / "lpb.conf.env").write_text("LPB_MAX_TOKENS_CONTEXT_RATIO=0.06\n")
    env = build.load_build_env(tmpdir.path)
    assert env["LPB_IMAGE_CLI"] == "ghcr.io/lpb-stack/devstack:cli"
    assert env["LPB_MAX_TOKENS_CONTEXT_RATIO"] == "0.06"


def test_build_load_env_missing_file(tmpdir):
    (tmpdir / "lpb.stack.env").write_text("A=1\n")
    try:
        build.load_build_env(tmpdir.path)
        assert False, "should raise FileNotFoundError"
    except FileNotFoundError as e:
        assert "lpb.conf.env" in str(e)


def test_build_load_env_missing_var(tmpdir):
    for name in ("lpb.stack.env", "lpb.conf.env"):
        (tmpdir / name).write_text("LPB_MAX_TOKENS_CONTEXT_RATIO=0.06\n")
    try:
        build.load_build_env(tmpdir.path)
        assert False, "should raise RuntimeError"
    except RuntimeError as e:
        assert "LPB_IMAGE_CLI" in str(e)


def test_build_load_env_expands_home(tmpdir):
    (tmpdir / "lpb.stack.env").write_text(
        "LPB_IMAGE_CLI=c\nLPB_IMAGE_WEB=w\nLPB_PI_FORK=f\nLPB_PI_REF=r\n"
        "LPB_CONFIG_FORK=c\nLPB_CONFIG_REF=m\nLPB_NODE_VERSION=n\nLPB_VSCODIUM_VERSION=v\n"
    )
    (tmpdir / "lpb.conf.env").write_text(
        "LPB_MAX_TOKENS_CONTEXT_RATIO=0.06\nLPB_STATE_DIR=${HOME}/.lpb-stack/state\n"
    )
    env = build.load_build_env(tmpdir.path)
    assert env["LPB_STATE_DIR"] == os.path.expanduser("~") + "/.lpb-stack/state"


def test_build_build_args_with_fake_git(tmpdir):
    env = {
        "LPB_PI_FORK": "fork", "LPB_PI_REF": "ref",
        "LPB_CONFIG_FORK": "cfg", "LPB_CONFIG_REF": "main",
        "LPB_NODE_VERSION": "24", "LPB_VSCODIUM_VERSION": "v",
        "LPB_MAX_TOKENS_CONTEXT_RATIO": "0.06",
        "LPB_IMAGE_CLI": "cli", "LPB_IMAGE_WEB": "web",
    }
    (tmpdir / "VERSION").write_text("0.9.9-test\n")
    runner = _fake_runner({
        "ls-remote": ("abc123HEAD...\trefs/heads/ref\n", 0),
        "rev-parse": ("beef123\n", 0),
    })
    now = datetime.datetime(2026, 8, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
    args = build.build_args(env, root=tmpdir.path, now=now, runner=runner)
    flat = " ".join(args)
    assert "PI_HEAD_SHA=abc123HEAD..." in flat
    assert "IMAGE_REVISION=beef123" in flat
    assert "IMAGE_BUILT=2026-08-10T12:00:00Z" in flat
    assert "LPB_VERSION=0.9.9-test" in flat
    assert "--build-arg" in flat


def test_build_build_args_git_fail(tmpdir):
    env = {
        "LPB_PI_FORK": "fork", "LPB_PI_REF": "ref",
        "LPB_CONFIG_FORK": "cfg", "LPB_CONFIG_REF": "main",
        "LPB_NODE_VERSION": "24", "LPB_VSCODIUM_VERSION": "v",
        "LPB_MAX_TOKENS_CONTEXT_RATIO": "0.06",
        "LPB_IMAGE_CLI": "cli", "LPB_IMAGE_WEB": "web",
    }
    runner = _fake_runner({"ls-remote": ("", 128), "rev-parse": ("", 128)})
    now = datetime.datetime(2026, 8, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
    args = build.build_args(env, root=tmpdir.path, now=now, runner=runner)
    flat = " ".join(args)
    assert "PI_HEAD_SHA=unknown" in flat
    assert "IMAGE_REVISION=unknown" in flat
    assert "LPB_VERSION=unknown" in flat


def test_build_command_shape(tmpdir):
    cmd = build.build_command("cli", "img:cli", ["--build-arg", "X=1"], root=tmpdir)
    assert cmd[0] == "docker" and cmd[1] == "buildx"
    assert "--target" in cmd and cmd[cmd.index("--target") + 1] == "cli"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "img:cli"
    assert "--platform" in cmd and cmd[cmd.index("--platform") + 1] == "linux/amd64"
    assert cmd[-1] == "."
    assert "--push" not in cmd
    pushed = build.build_command("web", "img:web", [], push=True, root=tmpdir)
    assert pushed[-2:] == ["--push", "."]


# ═══════════════════════════════════════════════════════════════════════════
# browser_state_cleanup
# ═══════════════════════════════════════════════════════════════════════════

def _make_session_dirs(tmpdir, names_and_ages):
    """Create dirs in tmpdir; return {name: Path}. Ages in days (0 = now)."""
    now = time.time()
    paths = {}
    for name, age_days in names_and_ages:
        d = tmpdir / name
        d.mkdir()
        os.utime(d, (now - age_days * 86400, now - age_days * 86400))
        paths[name] = d
    return paths


def test_bsc_session_dirs(tmpdir):
    assert bsc.session_dirs(tmpdir / "nope") == []
    (tmpdir / "a").mkdir(); (tmpdir / "file").write_text("x")
    names = sorted(p.name for p in bsc.session_dirs(tmpdir))
    assert names == ["a"]


def test_bsc_prune_by_age(tmpdir):
    now = datetime.datetime.now()
    dirs = list(_make_session_dirs(tmpdir, [("old", 10), ("mid", 3), ("new", 1)]).values())
    removed, remaining = bsc.prune_by_age(dirs, 7, now=now)
    assert [d.name for d in removed] == ["old"]
    assert sorted(d.name for d in remaining) == ["mid", "new"]


def test_bsc_prune_by_count(tmpdir):
    dirs = list(_make_session_dirs(tmpdir, [("a", 5), ("b", 4), ("c", 3)]).values())
    removed, remaining = bsc.prune_by_count(dirs, 2)
    assert [d.name for d in removed] == ["a"]
    assert sorted(d.name for d in remaining) == ["b", "c"]


def test_bsc_cleanup_end_to_end(tmpdir):
    now = datetime.datetime.now()
    _make_session_dirs(tmpdir, [("old", 10), ("mid", 3), ("new", 1)])
    removed, remaining = bsc.cleanup(tmpdir.path, max_age_days=7, max_count=20, remove=True, now=now)
    assert [d.name for d in removed] == ["old"]
    assert sorted(d.name for d in remaining) == ["mid", "new"]
    assert not (tmpdir / "old").exists()
    assert (tmpdir / "mid").exists()


def test_bsc_cleanup_dry_run(tmpdir):
    now = datetime.datetime.now()
    _make_session_dirs(tmpdir, [("old", 10), ("new", 1)])
    removed, remaining = bsc.cleanup(tmpdir.path, max_age_days=7, max_count=20, remove=False, now=now)
    assert [d.name for d in removed] == ["old"]
    assert (tmpdir / "old").exists()  # nothing deleted on dry run


def test_bsc_cleanup_count_trim(tmpdir):
    now = datetime.datetime.now()
    _make_session_dirs(tmpdir, [("s1", 1), ("s2", 1), ("s3", 1), ("s4", 1)])
    removed, remaining = bsc.cleanup(tmpdir.path, max_age_days=1, max_count=2, remove=True, now=now)
    # age cutoff is strict (<), all fresh enough; count trims to 2
    assert len(removed) == 2 and len(remaining) == 2
    assert len(list(tmpdir.iterdir())) == 2


def test_bsc_cleanup_missing_state_dir(tmpdir):
    removed, remaining = bsc.cleanup(tmpdir / "nonexistent", remove=True)
    assert removed == [] and remaining == []


# ═══════════════════════════════════════════════════════════════════════════
# NOTE: These tests are stubs for lpb-config features (repo listing,
# mirror management) that are not yet implemented. They are skipped
# until the underlying functions exist.
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# lpb_config
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


def _quiet_console():
    return log_mod.Console(color=False, out=io.StringIO(), err=io.StringIO())


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


# ─── lpb_config workspace sync ─────────────────────────────────────────────

def _bare_remote(tmpdir, name, branch="dev"):
    """Bare remote with one commit + tag 0.0.1 on *branch*; returns (remote, src_work)."""
    remote = tmpdir / "remotes" / f"{name}.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    work = tmpdir / "src" / name
    work.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(work), "checkout", "-q", "-b", branch], check=True)
    (work / "f").write_text("one")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "one"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", branch], check=True)
    # Point the remote HEAD at the pushed branch so plain clones check it out
    subprocess.run(["git", "-C", str(remote), "symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True)
    subprocess.run(["git", "-C", str(work), "tag", "0.0.1"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "0.0.1"], check=True)
    return remote, work


def _push_branch(work, branch, content="two"):
    """Add a commit on *branch* of src work tree and push it."""
    subprocess.run(["git", "-C", str(work), "checkout", "-q", branch], check=True)
    (work / "f").write_text(content)
    subprocess.run(["git", "-C", str(work), "commit", "-qam", "next"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", branch], check=True)


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


# ═══════════════════════════════════════════════════════════════════════════
# _stack_lib: pipeline detection + VERSION math
# ═══════════════════════════════════════════════════════════════════════════

def test_stack_lib_detect_pipeline_tag_override():
    assert sl.detect_pipeline("dev") == "dev"
    assert sl.detect_pipeline("main") == "main"
    assert sl.detect_pipeline(None) in ("dev", "main")


def test_stack_lib_detect_pipeline_env_tag():
    with mock.patch.dict(os.environ, {"LPB_IMAGE_TAG": "main"}, clear=False):
        assert sl.detect_pipeline(None) == "main"


def test_stack_lib_expected_branch():
    assert sl.expected_branch("pi", "dev") == "lpb-dev"
    assert sl.expected_branch("pi", "main") == "lpb"
    assert sl.expected_branch("devstack", "dev") == "dev"
    assert sl.expected_branch("devstack", "main") == "main"
    assert sl.expected_branch("nope", "dev") == ""  # not a workspace repo


def test_stack_lib_parse_version():
    assert sl.parse_version("0.0.57-lpb-dev") == (0, 0, 57, "-lpb-dev")
    assert sl.parse_version("1.2.3-lpb") == (1, 2, 3, "-lpb")
    assert sl.parse_version("garbage") is None
    assert sl.parse_version("0.0.57") is None  # suffix required


def test_stack_lib_bump_version():
    assert sl.bump_version("0.0.57-lpb-dev") == "0.0.58-lpb-dev"
    assert sl.bump_version("0.0.57-lpb") == "0.0.58-lpb"          # suffix preserved
    assert sl.bump_version("0.0.9-lpb-dev", "minor") == "0.1.0-lpb-dev"
    assert sl.bump_version("0.9.9-lpb", "major") == "1.0.0-lpb"
    for bad, kind in (("nope", "patch"), ("0.0.57", "patch"), ("0.0.1-lpb-dev", "bogus")):
        try:
            sl.bump_version(bad, kind)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass


# ─── lpb-devstack: VERSION bumping ────────────────────────────────────────

def _devstack_root_patch(root, tmpdir):
    """Point stack version discovery at *root* (context manager)."""
    return mock.patch.multiple(
        ver_mod,
        _DEVSTACK_ROOT=root,
        WORKSPACE_ROOT=tmpdir / "nowhere",
        _VERSION_FILE=None,
    )


def test_devstack_bump_patch(tmpdir):
    root = tmpdir / "devstack"
    root.mkdir()
    (root / "VERSION").write_text("0.0.57-lpb-dev\n")
    with _devstack_root_patch(root, tmpdir):
        code = ld.cmd_bump(_quiet_console(), no_commit=True)
    assert code == 0
    assert (root / "VERSION").read_text().strip() == "0.0.58-lpb-dev"


def test_devstack_bump_minor_and_set(tmpdir):
    root = tmpdir / "devstack"
    root.mkdir()
    (root / "VERSION").write_text("0.0.9-lpb-dev\n")
    with _devstack_root_patch(root, tmpdir):
        assert ld.cmd_bump(_quiet_console(), minor=True, no_commit=True) == 0
        assert (root / "VERSION").read_text().strip() == "0.1.0-lpb-dev"
        # explicit --set (same value → no-op, still 0)
        assert ld.cmd_bump(_quiet_console(), set_version="0.1.0-lpb-dev", no_commit=True) == 0
        assert (root / "VERSION").read_text().strip() == "0.1.0-lpb-dev"
        # invalid --set rejected
        assert ld.cmd_bump(_quiet_console(), set_version="1.2.3", no_commit=True) == 1
        assert (root / "VERSION").read_text().strip() == "0.1.0-lpb-dev"


def test_devstack_bump_commits(tmpdir):
    root = tmpdir / "devstack"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "VERSION").write_text("0.0.57-lpb-dev\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    with _devstack_root_patch(root, tmpdir):
        code = ld.cmd_bump(_quiet_console())  # commit (no push)
    assert code == 0
    r = subprocess.run(
        ["git", "-C", str(root), "show", "HEAD:VERSION"],
        capture_output=True, text=True)
    assert r.stdout.strip() == "0.0.58-lpb-dev"


def test_devstack_bump_missing_version(tmpdir):
    with mock.patch.object(ver_mod, "_VERSION_FILE", None), \
         mock.patch.object(ver_mod, "_DEVSTACK_ROOT", tmpdir / "nope"), \
         mock.patch.object(ver_mod, "WORKSPACE_ROOT", tmpdir / "nope2"):
        assert ld.cmd_bump(_quiet_console(), no_commit=True) == 1


# ─── lpb-devstack: repo tagging ───────────────────────────────────────────

def test_devstack_tag_repos(tmpdir):
    remote, _src = _bare_remote(tmpdir, "pi", "lpb-dev")
    # Local workspace clone (cmd_tag_repos tags via the workspace repos)
    ws = tmpdir / "workspace" / "pi"
    ws.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--branch", "lpb-dev", str(remote), str(ws)], check=True)
    env = mock.patch.dict(os.environ, {"LPB_STACK_REMOTE_BASE": str(tmpdir / "remotes")})
    patch_repos = mock.patch.object(sl, "TAG_REPOS", [("pi", "lpb-dev", "lpb")])
    patch_ws = mock.patch.object(ws_mod, "WORKSPACE_ROOT", tmpdir / "workspace")
    for p in (env, patch_repos, patch_ws):
        p.start()
    try:
        code = ld.cmd_tag_repos(_quiet_console(), pipeline="dev", version="0.0.58-lpb-dev")
        assert code == 0
        r = subprocess.run(
            ["git", "ls-remote", str(remote), "refs/tags/0.0.58-lpb-dev"],
            capture_output=True, text=True)
        assert "0.0.58-lpb-dev" in r.stdout
        # idempotent: second run reports "already exists" and succeeds
        assert ld.cmd_tag_repos(_quiet_console(), pipeline="dev", version="0.0.58-lpb-dev") == 0
        # main pipeline targets the 'lpb' branch (absent on this remote → fail fast)
        assert ld.cmd_tag_repos(_quiet_console(), pipeline="main", version="0.0.58-lpb") == 1
    finally:
        for p in (env, patch_repos, patch_ws):
            p.stop()


def test_devstack_tag_repos_missing_clone(tmpdir):
    with mock.patch.object(sl, "TAG_REPOS", [("pi", "lpb-dev", "lpb")]), \
         mock.patch.object(ws_mod, "WORKSPACE_ROOT", tmpdir / "empty-ws"):
        cons = _quiet_console()
        assert ld.cmd_tag_repos(cons, pipeline="dev", version="0.0.58-lpb-dev") == 1
        assert "workspace sync" in cons.err.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# validate
# ═══════════════════════════════════════════════════════════════════════════

def test_validate_checker_counts():
    cons = _quiet_console()
    c = validate.Checker(cons)
    c.pass_("a"); c.pass_("b"); c.fail("x"); c.warn("w")
    assert c.checks == 4 and c.errors == 1


def test_validate_build_tools(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)
    with mock.patch.object(validate, "which", side_effect=lambda name: "/bin/" + name if name != "make" else None), \
         mock.patch.object(validate, "SQLITE_LIB_DIRS", [str(tmpdir)]):
        (tmpdir / "libsqlite3.so.0").touch()
        validate.check_build_tools(c, cons)
    assert c.checks == 6 and c.errors == 1   # make missing, sqlite present


def test_validate_sqlite_missing(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)
    with mock.patch.object(validate, "SQLITE_LIB_DIRS", [str(tmpdir)]), \
         mock.patch.object(validate, "which", side_effect=lambda name: "/bin/" + name):
        validate.check_build_tools(c, cons)
    assert c.errors == 1


def test_validate_sudo_ok(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)

    def fake_run(args, timeout=15, cwd=None):
        if args == ["sudo", "-n", "cat", "/etc/sudoers.d/nopasswd"]:
            return "lpb ALL=(ALL) NOPASSWD:ALL", "", 0
        if args == ["sudo", "-n", "true"]:
            return "", "", 0
        return "", "", 1

    with mock.patch.object(validate, "run_cmd", side_effect=fake_run):
        validate.check_sudo(c, cons)
    assert c.errors == 0


def test_validate_sudo_missing(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)
    with mock.patch.object(validate, "run_cmd", return_value=("", "No such file", 1)):
        validate.check_sudo(c, cons)
    assert c.errors == 1


def test_validate_native_modules(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)
    ext = tmpdir / "git" / "github.com" / "x" / "repo"
    node = ext / "node_modules" / "better-sqlite3" / "build" / "Release" / "better_sqlite3.node"
    node.parent.mkdir(parents=True)
    node.touch()
    calls = {"cwd": None}
    with mock.patch.object(validate, "EXT_BASE", ext), \
         mock.patch.object(
             validate, "run_cmd",
             side_effect=lambda args, timeout=60, cwd=None: (calls.update(cwd=cwd) or ("", "", 0)),
         ):
        validate.check_native_modules(c, cons)
    assert c.errors == 0
    assert calls["cwd"] == str(node.parent.parent)  # node -e runs from ext_dir


def test_validate_extensions(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)
    ext = tmpdir / "git"
    (ext / "github.com" / "lpb-stack" / "lemonade-pi-plugin" / "package.json").parent.mkdir(parents=True)
    (ext / "github.com" / "lpb-stack" / "lemonade-pi-plugin" / "package.json").touch()
    (ext / "github.com" / "lpb-stack" / "lpb-memory" / "package.json").parent.mkdir(parents=True)
    (ext / "github.com" / "lpb-stack" / "lpb-memory" / "package.json").touch()
    with mock.patch.object(validate, "EXT_BASE", ext):
        validate.check_extensions(c, cons)
    assert c.errors == 0 and c.checks == 2


def test_validate_pi_cli_missing(tmpdir):
    cons = _quiet_console()
    c = validate.Checker(cons)
    with mock.patch.object(validate, "which", return_value=None):
        validate.check_pi_cli(c, cons)
    assert c.errors == 1


# ═══════════════════════════════════════════════════════════════════════════
# install_browser
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# install_openspec
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# Harness
# ═══════════════════════════════════════════════════════════════════════════

class _TmpDir(Path):
    """Path-like tmpdir for tests (also exposes ``.path``)."""

    @property
    def path(self) -> "_TmpDir":
        return self


def _tests():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            yield name, fn


def main() -> int:
    print("=" * 60)
    print("lpb-stack + ported-tools test suite")
    print("=" * 60)
    import inspect
    passed = failed = 0
    tmp = Path(tempfile.mkdtemp(prefix="lpb-stack-tests-"))
    try:
        for name, fn in _tests():
            tmpdir = _TmpDir(tmp) / name
            tmpdir.mkdir(parents=True, exist_ok=True)
            try:
                if inspect.signature(fn).parameters:
                    fn(tmpdir)
                else:
                    fn()
                print(f"  PASS  {name}")
                passed += 1
            except SystemExit as e:
                if e.code == 0:
                    print(f"  PASS  {name}")
                    passed += 1
                else:
                    print(f"  FAIL  {name}: unexpected exit {e.code}")
                    failed += 1
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL  {name}: {type(e).__name__}: {e}")
                failed += 1
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 60)
    print(f"Results: {passed}/{passed + failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
