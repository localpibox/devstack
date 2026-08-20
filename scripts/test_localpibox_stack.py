#!/usr/bin/env python3
"""localpibox._stack_lib tests: pipeline detection (tag override,
env tag), expected branch, VERSION parse/bump math."""
from __future__ import annotations

from testharness import run_lpbx_suite

import os
from unittest import mock

from localpibox import _stack_lib as sl


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


def main() -> int:
    return run_lpbx_suite("_stack_lib tests", globals())


if __name__ == "__main__":
    raise SystemExit(main())
