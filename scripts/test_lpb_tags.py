#!/usr/bin/env python3
"""lpb.py image-tag tests: --tag selection (dev/main/latest/custom,
short flags, web mode), resolve_cli_image/resolve_web_image defaults,
and --update version pinning.

Part of the lpb.py test suite (entry point: test_lpb.py).
"""
from __future__ import annotations

from testharness import (
    _OutputCapture,
    make_module,
    reset_mock,
    run_lpb_suite,
)

# ─── Image tag tests ──────────────────────────────────────────────────────────

def test_tag_dev():
    """--tag dev sets image_tag to dev."""
    print("TEST: --tag dev")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "dev"])
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_main():
    """--tag main sets image_tag to main."""
    print("TEST: --tag main")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "main"])
    assert mod.cfg.image_tag == "main", f"Expected 'main', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_latest():
    """--tag latest sets image_tag to latest."""
    print("TEST: --tag latest")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "latest"])
    assert mod.cfg.image_tag == "latest", f"Expected 'latest', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_custom_version():
    """--tag 0.0.27-lpb-dev sets image_tag to custom version."""
    print("TEST: --tag custom version")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "0.0.27-lpb-dev"])
    assert mod.cfg.image_tag == "0.0.27-lpb-dev", f"Expected '0.0.27-lpb-dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_with_project():
    """--tag dev /path sets image_tag and project_dir."""
    print("TEST: --tag dev /tmp")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--tag", "dev", "/tmp"])
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    assert mod.cfg.project_dir == "/tmp", f"Expected '/tmp', got {mod.cfg.project_dir!r}"
    print("  PASS\n")


def test_update_with_tag():
    """--update --tag dev sets command=update and image_tag=dev."""
    print("TEST: --update --tag dev")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--update", "--tag", "dev"])
    assert mod.cfg.command == "update", f"Expected 'update', got {mod.cfg.command!r}"
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_web_mode():
    """--web --tag dev sets web_mode and image_tag."""
    print("TEST: --web --tag dev")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--web", "--tag", "dev"])
    assert mod.cfg.web_mode, "Expected web_mode=True"
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_resolve_cli_image_dev():
    """resolve_cli_image('dev') returns dev-cli suffix."""
    print("TEST: resolve_cli_image('dev')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_cli_image("dev")
    assert image.endswith("-cli") or image.endswith(":dev-cli"), f"Expected -cli suffix, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_cli_image_main():
    """resolve_cli_image('main') returns main/cli suffix."""
    print("TEST: resolve_cli_image('main')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_cli_image("main")
    assert image.endswith("-cli") or image.endswith(":main-cli"), f"Expected -cli suffix, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_cli_image_custom():
    """resolve_cli_image('0.0.27-lpb-dev') returns versioned image."""
    print("TEST: resolve_cli_image('0.0.27-lpb-dev')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_cli_image("0.0.27-lpb-dev")
    assert "0.0.27-lpb-dev" in image, f"Expected version in image, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_web_image_dev():
    """resolve_web_image('dev') returns dev-web suffix."""
    print("TEST: resolve_web_image('dev')")
    reset_mock()
    mod = make_module()
    image = mod.resolve_web_image("dev")
    assert image.endswith("-web") or image.endswith(":dev-web"), f"Expected -web suffix, got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_cli_image_default():
    """resolve_cli_image('') with no pin defaults to the dev pipeline."""
    print("TEST: resolve_cli_image('') -> dev pipeline")
    reset_mock()
    mod = make_module()
    mod.LAST_VERSION_FILE.unlink(missing_ok=True)  # no pin in this scenario
    mod._get_remote_version = lambda branch="dev": "0.0.99-lpb-dev"
    image = mod.resolve_cli_image("")
    assert image == "ghcr.io/lpb-stack/devstack:0.0.99-lpb-dev-cli", f"got {image}"
    print(f"  Image: {image}")
    print("  PASS\n")


def test_resolve_cli_image_default_offline():
    """No pin + offline -> floating :dev-cli/:dev-web tags (real registry tags).

    Regression guard: the old fallback used the bare :cli/:web tags, which CI
    never publishes -> 'manifest unknown' on every fresh install.
    """
    print("TEST: resolve_cli_image('') offline -> :dev-cli")
    reset_mock()
    mod = make_module()
    mod.LAST_VERSION_FILE.unlink(missing_ok=True)  # no pin in this scenario
    mod._get_remote_version = lambda branch="dev": ""
    image = mod.resolve_cli_image("")
    assert image == "ghcr.io/lpb-stack/devstack:dev-cli", f"got {image}"
    web = mod.resolve_web_image("")
    assert web == "ghcr.io/lpb-stack/devstack:dev-web", f"got {web}"
    print("  PASS\n")


def test_resolve_cli_image_default_pinned():
    """A pinned last-version wins over the remote (no network consulted)."""
    print("TEST: resolve_cli_image('') with pin")
    reset_mock()
    mod = make_module()

    def no_remote(branch="dev"):
        raise AssertionError("remote must not be consulted when pinned")

    mod._get_remote_version = no_remote
    # Pin a version in the isolated HOME (test's last-version file)
    mod.LAST_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    mod.LAST_VERSION_FILE.write_text("0.0.50-lpb-dev\n")
    image = mod.resolve_cli_image("")
    assert image == "ghcr.io/lpb-stack/devstack:0.0.50-lpb-dev-cli", f"got {image}"
    print("  PASS\n")


def test_cmd_update_saves_version():
    """--update (no tag) pulls the dev pipeline and pins the new version.

    Regression guard: the old save loop matched the version regex against the
    full tag including the -cli/-web suffix, so it never saved. A bare `lpb`
    after `lpb --update` then fell back to the dead :cli tag and failed with
    'manifest unknown' even though devstack images were already local.
    """
    print("TEST: --update saves version")
    reset_mock()
    mod = make_module()
    mod.self_update = lambda: None
    mod._get_remote_version = lambda branch="dev": "0.0.99-lpb-dev"
    pulled = []
    mod.ContainerClient.images_pull = lambda self, name: pulled.append(name) or 0
    mod.parse_cli(["--update"])
    mod.apply_overrides()
    with _OutputCapture():
        mod.cmd_update()
    assert len(pulled) == 2, f"expected cli+web pulls, got {pulled}"
    assert pulled[0] == "ghcr.io/lpb-stack/devstack:0.0.99-lpb-dev-cli", f"got {pulled}"
    assert pulled[1] == "ghcr.io/lpb-stack/devstack:0.0.99-lpb-dev-web", f"got {pulled}"
    assert mod._load_last_version() == "0.0.99-lpb-dev", \
        f"last-version not saved, got {mod._load_last_version()!r}"
    print("  PASS\n")


def test_dev_short_flag():
    """--dev is shorthand for --tag dev."""
    print("TEST: --dev short flag")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--dev"])
    assert mod.cfg.image_tag == "dev", f"Expected 'dev', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_main_short_flag():
    """--main is shorthand for --tag main."""
    print("TEST: --main short flag")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--main"])
    assert mod.cfg.image_tag == "main", f"Expected 'main', got {mod.cfg.image_tag!r}"
    print("  PASS\n")


def test_tag_wins_over_short_flags():
    """Explicit --tag / --version win when combined with --dev/--main."""
    print("TEST: --tag wins over short flags")
    reset_mock()
    mod = make_module()
    mod.parse_cli(["--dev", "--tag", "main"])
    assert mod.cfg.image_tag == "main", f"Expected 'main', got {mod.cfg.image_tag!r}"
    mod2 = make_module()
    mod2.parse_cli(["--main", "--version", "0.0.9-lpb-dev"])
    assert mod2.cfg.image_tag == "0.0.9-lpb-dev", f"Expected pinned version, got {mod2.cfg.image_tag!r}"
    print("  PASS\n")


TESTS = [
    test_tag_dev,
    test_tag_main,
    test_tag_latest,
    test_tag_custom_version,
    test_tag_with_project,
    test_update_with_tag,
    test_tag_web_mode,
    test_dev_short_flag,
    test_main_short_flag,
    test_tag_wins_over_short_flags,
    test_resolve_cli_image_dev,
    test_resolve_cli_image_main,
    test_resolve_cli_image_custom,
    test_resolve_web_image_dev,
    test_resolve_cli_image_default,
    test_resolve_cli_image_default_offline,
    test_resolve_cli_image_default_pinned,
    test_cmd_update_saves_version,
]


def main() -> int:
    return run_lpb_suite("lpb.py image-tag tests", TESTS)


if __name__ == "__main__":
    raise SystemExit(main())
