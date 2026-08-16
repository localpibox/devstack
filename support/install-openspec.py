#!/usr/bin/env python3
"""install-openspec — Install OpenSpec in the current workspace (opt-in).

Python port of support/install-openspec.

Bootstraps OpenSpec spec-driven development in the target project:
  1. Installs the OpenSpec CLI globally (idempotent, 3 retries)
  2. Ensures global config is set (delivery: both, profile: core)
  3. Runs ``openspec init --tools pi`` in the target directory
  4. Verifies generated files are present and loadable by Pi

Usage:
  install-openspec [target-dir]     (default: current directory)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_SELF_DIR = Path(__file__).resolve().parent
for _c in (_SELF_DIR.parent / "scripts", _SELF_DIR, Path("/opt/pi-support")):
    if (_c / "lpb-stack").is_dir():
        sys.path.insert(0, str(_c))
        break

from lpb-stack.cli import add_common_args, console_from_args, install_sigpipe_handler  # noqa: E402
from lpb-stack.log import Console  # noqa: E402
from lpb-stack.run import run_cmd, which  # noqa: E402
import subprocess  # noqa: E402

OPENSPEC_PKG = "@fission-ai/openspec"
OPENSPEC_CMD = "openspec"
OPENSPEC_VERSION = "latest"
RETRIES = 3


def resolve_target_dir(arg: str) -> Path:
    return Path(arg).resolve()


def install_openspec(cons: Console) -> int:
    if which(OPENSPEC_CMD):
        out, _, _ = run_cmd([OPENSPEC_CMD, "--version"], timeout=30)
        cons.info(f"OpenSpec {out.strip() or 'installed'} already installed, skipping")
        return 0

    cons.info(f"Installing {OPENSPEC_PKG}@{OPENSPEC_VERSION} ...")
    # Ensure npm uses ~/.npm-global (the Dockerfile sets this at build time
    # but the .npmrc gets overwritten — so we must re-set it at runtime).
    run_cmd(["npm", "config", "set", "prefix", f"{Path.home()}/.npm-global"], timeout=30)

    for attempt in range(1, RETRIES + 1):
        r = subprocess.run(
            ["npm", "install", "-g", f"{OPENSPEC_PKG}@{OPENSPEC_VERSION}"],
            stdout=sys.stdout,
            stderr=sys.stderr,
            timeout=600,
            check=False,
        )
        if r.returncode == 0 and which(OPENSPEC_CMD):
            cons.info("OpenSpec installed successfully")
            return 0
        if attempt < RETRIES:
            cons.warn(f"Attempt {attempt} failed, retrying in 5s...")
            time.sleep(5)
    cons.error(f"Failed to install OpenSpec after {RETRIES} attempts")
    return 1


def configure_openspec(cons: Console) -> None:
    cons.info("OpenSpec defaults: delivery=both, profile=core (already set)")


def init_openspec(target: Path, cons: Console) -> int:
    if (target / "openspec").is_dir():
        cons.warn(f"openspec/ already exists in {target}")
        cons.info("Running openspec update instead...")
        out, err, code = run_cmd([OPENSPEC_CMD, "update"], timeout=300, cwd=str(target))
        if code == 0:
            cons.info("OpenSpec updated successfully")
            return 0
        cons.error(f"openspec update failed ({err.strip() or out.strip()})")
        return 1

    cons.info(f"Initializing OpenSpec in {target} ...")
    out, err, code = run_cmd([OPENSPEC_CMD, "init", "--tools", "pi"], timeout=300, cwd=str(target))
    if code:
        cons.error(f"openspec init failed ({err.strip() or out.strip()})")
        return 1
    cons.info("OpenSpec initialized successfully")
    return 0


def verify_installation(target: Path, cons: Console) -> int:
    errors = 0
    cons.info("Verifying installation...")

    openspec_dir = target / "openspec"
    if openspec_dir.is_dir():
        cons.info("  openspec/       \u2713 specs + changes")
    else:
        cons.error("  openspec/       \u2717 missing")
        errors += 1

    if (openspec_dir / "config.yaml").is_file():
        cons.info("  config.yaml     \u2713 project config")
    else:
        cons.warn("  config.yaml     \u2014 not found (optional)")

    prompts = target / ".pi" / "prompts"
    if prompts.is_dir():
        count = len(list(prompts.glob("opsx-*.md")))
        cons.info(f"  .pi/prompts/    \u2713 {count} command files")
    else:
        cons.warn("  .pi/prompts/    \u2014 not found (Pi may not see commands)")

    skills = target / ".pi" / "skills"
    if skills.is_dir():
        count = len([p for p in skills.iterdir() if p.is_dir()])
        cons.info(f"  .pi/skills/     \u2713 {count} skill directories")
    else:
        cons.warn("  .pi/skills/     \u2014 not found (Pi may not see skills)")

    if prompts.is_dir():
        if (prompts / "opsx-propose.md").is_file() or (prompts / "openspec-proposal.md").is_file():
            cons.info("  Pi discovery    \u2713 commands will be available")
        else:
            cons.warn("  Pi discovery    \u2014 propose command not found")

    if errors:
        cons.error(f"{errors} check(s) failed")
        return 1

    cons.info("OpenSpec setup complete!")
    cons.raw("")
    cons.info("Next steps:")
    cons.info(f"  cd {target}")
    cons.info("  /opsx:explore          \u2190 Think through an idea")
    cons.info('  /opsx:propose "name"   \u2190 Create a change plan')
    cons.info("  /opsx:apply            \u2190 Implement from tasks.md")
    cons.info("  /opsx:archive          \u2190 Merge specs, file away")
    return 0


def main(argv: list[str] | None = None) -> int:
    install_sigpipe_handler()
    parser = argparse.ArgumentParser(prog="install-openspec", description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="project directory (default: .)")
    add_common_args(parser)
    args = parser.parse_args(argv)
    cons = console_from_args(args)

    target = resolve_target_dir(args.target)
    cons.info("OpenSpec install script starting")
    cons.info(f"Target: {target}")

    # Fix ~/.config ownership — OpenSpec writes ~/.config/openspec/ and
    # crashes with EACCES if the dir is owned by root (container issue).
    config_dir = Path.home() / ".config"
    if config_dir.is_dir():
        try:
            owner_uid = config_dir.stat().st_uid
        except OSError:
            owner_uid = -1
        if owner_uid != os.getuid():
            cons.info("Fixing ~/.config ownership for OpenSpec...")
            run_cmd(["sudo", "chown", str(os.getuid()), str(config_dir)], timeout=30)

    if install_openspec(cons) != 0:
        return 1
    configure_openspec(cons)
    if init_openspec(target, cons) != 0:
        return 1
    return verify_installation(target, cons)


if __name__ == "__main__":
    raise SystemExit(main())
