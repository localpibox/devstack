#!/usr/bin/env python3
"""localpibox.stack.release tests: docs readiness (verdict/gate math, state
from real git repos, docs-ready end-to-end with stub generate.py + fake
mike, idempotency, re-flag after drift) and release-state VERSION-only
conflict handling (devstack stable branch)."""
from __future__ import annotations

from testharness import run_lpbx_suite, _quiet_console

import os
import stat
import subprocess
from unittest import mock

from localpibox.stack import release as rel

_STUB_GENERATE = """#!/usr/bin/env python3
import pathlib
p = pathlib.Path(__file__).resolve().parent.parent / "docs"
p.mkdir(exist_ok=True)
(p / "repo-map.md").write_text("repo-map\\n")
print("stub generate ok")
"""

_FAKE_MIKE = """#!/bin/sh
if [ "$1" = "build" ]; then
  mkdir -p docs/site
  echo built > docs/site/.marker
fi
exit 0
"""


def _g(dir_, *args):
    return subprocess.run(["git", "-C", str(dir_), *args], check=True,
                          capture_output=True, text=True)


def _fake_stack(tmpdir):
    """Bare devstack remote + clone with dev (VERSION + doc/x.md) and docs
    (dev content + site machinery) branches. Returns the clone path."""
    remote = tmpdir / "remotes" / "devstack.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    clone = tmpdir / "devstack"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    _g(clone, "config", "user.email", "t@t")
    _g(clone, "config", "user.name", "t")
    _g(clone, "checkout", "-q", "-b", "dev")
    (clone / "VERSION").write_text("0.0.9-lpb-dev\n")
    (clone / "doc").mkdir()
    (clone / "doc" / "x.md").write_text("content v1\n")
    _g(clone, "add", ".")
    _g(clone, "commit", "-qm", "dev base")
    _g(clone, "push", "-q", "origin", "dev")
    _g(clone, "checkout", "-q", "-b", "docs", "dev")
    (clone / "mkdocs.yml").write_text("site_name: test\n")
    (clone / "DOCS.md").write_text("# docs\n")
    (clone / "scripts").mkdir()
    (clone / "scripts" / "generate.py").write_text(_STUB_GENERATE)
    _g(clone, "add", ".")
    _g(clone, "commit", "-qm", "machinery")
    _g(clone, "push", "-q", "origin", "docs")
    _g(clone, "checkout", "-q", "dev")
    return clone


def _patch_release(clone, tmpdir, with_mike=False):
    env = {"LPB_DOCS_PREVIEW": str(tmpdir / "preview")}
    if with_mike:
        binr = tmpdir / "bin"
        binr.mkdir(exist_ok=True)
        mike = binr / "mike"
        mike.write_text(_FAKE_MIKE)
        mike.chmod(0o755)
        env["PATH"] = f"{binr}{os.pathsep}{os.environ['PATH']}"
    return (mock.patch.multiple(
                rel,
                repo_path=lambda name: clone,
                get_version=lambda: (clone / "VERSION").read_text().strip(),
            ),
            mock.patch.dict(os.environ, env))


# ─── pure math ────────────────────────────────────────────────────────────

def test_docs_verdict_pure(tmpdir):
    assert rel._docs_verdict(None, "0.0.9-lpb", []) == "missing"
    assert rel._docs_verdict("0.0.8-lpb", "0.0.9-lpb", []) == "wrong-version"
    assert rel._docs_verdict("0.0.9-lpb", "0.0.9-lpb", ["doc/x.md"]) == "stale"
    assert rel._docs_verdict("0.0.9-lpb", "0.0.9-lpb", []) == "ready"


def test_docs_stable_version(tmpdir):
    assert rel._stable_version("0.0.9-lpb-dev") == "0.0.9-lpb"
    assert rel._stable_version("0.0.9-lpb") == "0.0.9-lpb"


def test_docs_gate_error_pure(tmpdir):
    ready = {"verdict": "ready", "target": "0.0.9-lpb",
             "flagged": "0.0.9-lpb", "flag_sha": "abc1234", "drift": []}
    assert rel._docs_gate_error(ready, all_noop=False) is None
    assert rel._docs_gate_error(ready, all_noop=True) is None
    missing = {**ready, "verdict": "missing", "flagged": None}
    msg = rel._docs_gate_error(missing, all_noop=False)
    assert msg and "docs-ready" in msg and "0.0.9-lpb" in msg
    # a no-op release (nothing to promote) is not gated on docs
    assert rel._docs_gate_error(missing, all_noop=True) is None
    stale = {**ready, "verdict": "stale", "drift": ["doc/a.md", "doc/b.md"]}
    msg = rel._docs_gate_error(stale, all_noop=False)
    assert msg and "doc/a.md" in msg and "doc/b.md" in msg
    unknown = {**ready, "verdict": "unknown"}
    assert rel._docs_gate_error(unknown, all_noop=False) is not None


# ─── state from real git repos ────────────────────────────────────────────

def test_docs_state_missing(tmpdir):
    clone = _fake_stack(tmpdir)
    p1, p2 = _patch_release(clone, tmpdir)
    with p1, p2:
        st = rel._docs_release_state()
    # machinery files (mkdocs.yml, DOCS.md, scripts/generate.py) must not
    # count as content drift
    assert st["verdict"] == "missing"
    assert st["target"] == "0.0.9-lpb"
    assert st["flagged"] is None
    assert st["drift"] == []


def test_docs_state_ready_then_stale(tmpdir):
    clone = _fake_stack(tmpdir)
    _g(clone, "checkout", "docs")
    (clone / "DOCS_READY").write_text("0.0.9-lpb\n")
    _g(clone, "add", "DOCS_READY")
    _g(clone, "commit", "-qm", "flag")
    _g(clone, "push", "-q", "origin", "docs")
    p1, p2 = _patch_release(clone, tmpdir)
    with p1, p2:
        assert rel._docs_release_state()["verdict"] == "ready"
    # doc content changes on dev after flagging → stale
    _g(clone, "checkout", "dev")
    (clone / "doc" / "x.md").write_text("content v2\n")
    _g(clone, "commit", "-qam", "doc update")
    _g(clone, "push", "-q", "origin", "dev")
    with p1, p2:
        st = rel._docs_release_state()
    assert st["verdict"] == "stale"
    assert st["drift"] == ["doc/x.md"]


def test_docs_state_wrong_version(tmpdir):
    clone = _fake_stack(tmpdir)
    _g(clone, "checkout", "docs")
    (clone / "DOCS_READY").write_text("0.0.8-lpb\n")
    _g(clone, "add", "DOCS_READY")
    _g(clone, "commit", "-qm", "flag")
    _g(clone, "push", "-q", "origin", "docs")
    p1, p2 = _patch_release(clone, tmpdir)
    with p1, p2:
        assert rel._docs_release_state()["verdict"] == "wrong-version"


# ─── release state: VERSION-only conflicts (devstack) ──────────────────────

def _fake_release_repo(tmpdir, diverge_main_doc=False):
    """Clone with dev (VERSION 0.0.9-lpb-dev, advanced doc) and a diverged
    main (VERSION stripped to 0.0.8-lpb + unique commit)."""
    remote = tmpdir / "remotes" / "rel.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    clone = tmpdir / "rel"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    _g(clone, "config", "user.email", "t@t")
    _g(clone, "config", "user.name", "t")
    _g(clone, "checkout", "-q", "-b", "dev")
    (clone / "VERSION").write_text("0.0.8-lpb-dev\n")
    (clone / "doc").mkdir()
    (clone / "doc" / "a.md").write_text("a\n")
    _g(clone, "add", ".")
    _g(clone, "commit", "-qm", "base")
    _g(clone, "push", "-q", "origin", "dev")
    _g(clone, "checkout", "-q", "-b", "main")
    (clone / "VERSION").write_text("0.0.8-lpb\n")
    if diverge_main_doc:
        (clone / "doc" / "a.md").write_text("main-side\n")
    _g(clone, "commit", "-qam", "strip")
    _g(clone, "push", "-q", "origin", "main")
    _g(clone, "checkout", "-q", "dev")
    (clone / "VERSION").write_text("0.0.9-lpb-dev\n")
    (clone / "doc" / "a.md").write_text("a2\n")
    _g(clone, "commit", "-qam", "advance")
    _g(clone, "push", "-q", "origin", "dev")
    return clone


def test_release_state_version_only_conflict_is_merge(tmpdir):
    """devstack: stable's stripped VERSION always conflicts with dev's by
    design — the strip step rewrites it, so feasibility is merge."""
    clone = _fake_release_repo(tmpdir)
    p1, p2 = _patch_release(clone, tmpdir)
    with p1, p2:
        st = rel._repo_release_state(clone, "dev", "main")
    assert st["conflicts"] == ["VERSION"]
    assert st["feasibility"] == "merge"


def test_release_state_real_conflict(tmpdir):
    clone = _fake_release_repo(tmpdir, diverge_main_doc=True)
    p1, p2 = _patch_release(clone, tmpdir)
    with p1, p2:
        st = rel._repo_release_state(clone, "dev", "main")
    assert "doc/a.md" in st["conflicts"]
    assert st["feasibility"] == "conflict"


# ─── docs-ready command end-to-end ────────────────────────────────────────

def test_docs_ready_flags_and_pushes(tmpdir):
    clone = _fake_stack(tmpdir)
    p1, p2 = _patch_release(clone, tmpdir, with_mike=True)
    with p1, p2:
        code = rel.cmd_release_docs_ready(assume_yes=True, cons=_quiet_console())
    assert code == 0
    remote = tmpdir / "remotes" / "devstack.git"
    flag = _g(remote, "show", "refs/heads/docs:DOCS_READY").stdout.strip()
    assert flag == "0.0.9-lpb"
    # dev content is merged into docs on the remote
    doc = _g(remote, "show", "refs/heads/docs:doc/x.md").stdout
    assert doc == "content v1\n"


def test_docs_ready_idempotent(tmpdir):
    clone = _fake_stack(tmpdir)
    p1, p2 = _patch_release(clone, tmpdir, with_mike=True)
    with p1, p2:
        assert rel.cmd_release_docs_ready(assume_yes=True,
                                          cons=_quiet_console()) == 0
        # second run: already ready → no-op
        assert rel.cmd_release_docs_ready(assume_yes=True,
                                          cons=_quiet_console()) == 0


def test_docs_ready_reflag_after_drift(tmpdir):
    clone = _fake_stack(tmpdir)
    p1, p2 = _patch_release(clone, tmpdir, with_mike=True)
    with p1, p2:
        assert rel.cmd_release_docs_ready(assume_yes=True,
                                          cons=_quiet_console()) == 0
    # doc content changes on dev → stale until re-flagged
    _g(clone, "checkout", "dev")
    (clone / "doc" / "x.md").write_text("content v3\n")
    _g(clone, "commit", "-qam", "v3")
    _g(clone, "push", "-q", "origin", "dev")
    with p1, p2:
        assert rel._docs_release_state()["verdict"] == "stale"
        assert rel.cmd_release_docs_ready(assume_yes=True,
                                          cons=_quiet_console()) == 0
        st = rel._docs_release_state()
    assert st["verdict"] == "ready"
    remote = tmpdir / "remotes" / "devstack.git"
    assert _g(remote, "show", "refs/heads/docs:doc/x.md").stdout == "content v3\n"


def main() -> int:
    return run_lpbx_suite("localpibox.stack release docs readiness", globals())


if __name__ == "__main__":
    import sys
    sys.exit(main())
