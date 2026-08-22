#!/usr/bin/env python3
"""localpibox.env tests: parse/expand/layer KEY=VALUE files,
env-chain loading, reference expansion, env-file discovery."""
from __future__ import annotations

from testharness import run_lpbx_suite

import os

from localpibox import env as env_mod


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


def main() -> int:
    return run_lpbx_suite("localpibox.env tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
