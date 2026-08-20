#!/usr/bin/env python3
"""browser-state-cleanup tests: session dir discovery, pruning by
age and count, end-to-end cleanup, dry-run, count trim, missing state dir."""
from __future__ import annotations

from testharness import run_lpbx_suite

import os
import time
import datetime
import importlib

bsc = importlib.import_module('browser-state-cleanup')


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


def main() -> int:
    return run_lpbx_suite("browser-state-cleanup tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
