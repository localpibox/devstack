#!/usr/bin/env python3
"""install-browser — Install Chrome + agent-browser (with system deps).

Python port of support/install-browser.

Downloads Chrome-for-Testing and runs ``agent-browser install --with-deps``,
which uses Playwright's dependency resolver to install only the exact
libraries needed for the downloaded Chrome version.

Usage:
  Inside container (as root or with sudo):
    /opt/devstack/install-browser
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

_SELF_DIR = Path(__file__).resolve().parent
for _c in (_SELF_DIR.parent / "scripts", _SELF_DIR, Path("/opt/pi-support")):
    if (_c / "localpibox").is_dir():
        sys.path.insert(0, str(_c))
        break

from localpibox.cli import add_common_args, console_from_args, install_sigpipe_handler  # noqa: E402
from localpibox.log import Console  # noqa: E402
from localpibox.run import is_container, run_cmd, which  # noqa: E402
import subprocess  # noqa: E402

CHROME_BASE = Path("/home/lpb/.agent-browser/browsers")
SYSTEM_CHROME = Path("/opt/google/chrome/chrome")
# Executable binaries inside the chrome-linux64/ payload (everything else
# is data/libs). Used to self-heal trees extracted without exec bits.
CHROME_EXECUTABLES = {"chrome", "chrome_crashpad_handler", "headless_shell"}
LAST_KNOWN_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)
DOWNLOAD_URL = (
    "https://storage.googleapis.com/chrome-for-testing-public/"
    "{version}/linux64/chrome-linux64.zip"
)


def fetch_stable_chrome_version() -> str:
    """Latest stable Chrome-for-Testing version string."""
    with urllib.request.urlopen(LAST_KNOWN_URL, timeout=30) as resp:
        data = json.load(resp)
    version = data["channels"]["Stable"]["version"]
    if not version:
        raise RuntimeError("Failed to fetch Chrome version")
    return version


def chrome_dir_for(version: str) -> Path:
    return CHROME_BASE / f"chrome-{version}"


def chrome_binary(version: str) -> Path:
    return chrome_dir_for(version) / "chrome-linux64" / "chrome"


def _ensure_executable(path: Path, cons: Console | None = None) -> None:
    """Restore the exec bit that Python's zipfile extractall drops.

    Chrome-for-Testing zips ship 0755 entries, but CPython's extractall()
    does not restore Unix modes — left alone, the binary is 0644 and every
    launch dies with PermissionError (errno 13).
    """
    if path.is_file() and not os.access(path, os.X_OK):
        path.chmod(path.stat().st_mode | 0o755)
        if cons:
            cons.warn(f"Restored missing exec bit on {path}")


def _restore_exec_bits(chrome_root: Path, cons: Console | None = None) -> int:
    """Self-heal an extracted Chrome tree: restore exec bits on the known
    binaries. Returns the number of files fixed. Chrome crashes at startup
    if chrome_crashpad_handler is not executable (PermissionError 13)."""
    fixed = 0
    for sub in (chrome_root, chrome_root / "chrome-linux64"):
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            if f.name in CHROME_EXECUTABLES and f.is_file() and not os.access(f, os.X_OK):
                f.chmod(f.stat().st_mode | 0o755)
                fixed += 1
    if fixed and cons:
        cons.warn(f"Restored missing exec bits on {fixed} Chrome binary(ies) under {chrome_root}")
    return fixed


def install_chrome(cons: Console) -> int:
    cons.info("Downloading latest Chrome for Testing...")
    try:
        version = fetch_stable_chrome_version()
    except Exception as exc:  # network/parse failures
        cons.error(f"Failed to fetch Chrome version: {exc}")
        return 1
    cons.info(f"Chrome version: {version}")

    bin_path = chrome_binary(version)
    if bin_path.is_file():
        if os.access(bin_path, os.X_OK) and not _restore_exec_bits(chrome_dir_for(version)):
            cons.warn(f"Chrome already installed at {chrome_dir_for(version)}")
            return 0
        # Self-heal: an earlier install may have extracted without exec bits
        # (Python's zipfile drops Unix modes) — restore and reuse.
        _restore_exec_bits(chrome_dir_for(version), cons)
        cons.warn(f"Chrome already installed at {chrome_dir_for(version)} (exec bits restored)")
        return 0

    chrome_dir_for(version).mkdir(parents=True, exist_ok=True)
    url = DOWNLOAD_URL.format(version=version)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        zip_path = Path(tmp.name)
    try:
        cons.info(f"Downloading {url} ...")
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            # Extract member-by-member and restore Unix modes: extractall()
            # drops exec bits, leaving the chrome binary unrunnable (0644).
            for member in zf.infolist():
                target = zf.extract(member, chrome_dir_for(version))
                if not member.is_dir():
                    mode = member.external_attr >> 16
                    if mode:
                        os.chmod(target, mode & 0o7777)
    finally:
        zip_path.unlink(missing_ok=True)

    if bin_path.is_file():
        _restore_exec_bits(chrome_dir_for(version), cons)  # belt & braces
        cons.info(f"Chrome extracted to {chrome_dir_for(version)}")
        return 0
    cons.error("Chrome extraction failed")
    return 1


def install_agent_browser(cons: Console) -> int:
    cons.info("Installing agent-browser with system dependencies...")
    if not which("agent-browser"):
        cons.error("agent-browser binary not found")
        return 1

    def _run_agent(*args: str) -> subprocess.CompletedProcess[str]:
        """Run agent-browser command, streaming stdout/stderr to the user."""
        r = subprocess.run(
            ["agent-browser"] + list(args),
            stdout=sys.stdout,
            stderr=sys.stderr,
            timeout=600,
            check=False,
        )
        return r

    result_install = _run_agent("install")
    if result_install.returncode != 0:
        cons.error("agent-browser install failed")
        return 1

    result_deps = _run_agent("install", "--with-deps")
    if result_deps.returncode != 0:
        cons.warn("Some system dependencies may be missing; Chrome may fail at runtime")

    cons.info("agent-browser installed successfully")

    # Container-safe defaults: Chrome needs --no-sandbox in a container.
    # agent-browser reads ~/.agent-browser/config.json (camelCase keys; the
    # "args" value is a comma-separated launch-arg list). MERGE the safe set
    # into any existing config instead of skipping it — an existing file
    # (user-customized, or from an older stack) must not silence the
    # container-safe defaults.
    config_path = Path.home() / ".agent-browser" / "config.json"
    existed = config_path.is_file()
    config = {}
    if existed:
        try:
            loaded = json.loads(config_path.read_text())
            if isinstance(loaded, dict):
                config = loaded
        except (json.JSONDecodeError, OSError):
            cons.warn(f"Existing {config_path} is unreadable — overwriting")
    safe_args = ["--no-sandbox", "--no-first-run", "--disable-gpu", "--disable-crashpad"]
    existing = [a.strip() for a in str(config.get("args", "")).replace("\n", ",").split(",") if a.strip()]
    merged = existing + [a for a in safe_args if a not in existing]
    config["args"] = ",".join(merged)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    if not existed:
        cons.info(f"Created container-safe config: {config_path}")
    elif merged != existing:
        cons.info(f"Merged container-safe args into {config_path}")
    else:
        cons.info(f"Container-safe args already present in {config_path}")

    return 0


def verify_installation(cons: Console) -> int:
    cons.info("Verifying installation...")
    errors = 0

    chrome_bin = next(CHROME_BASE.glob("chrome-*/chrome-linux64/chrome"), None)
    if not chrome_bin:
        chrome_bin = SYSTEM_CHROME if SYSTEM_CHROME.is_file() else None

    if chrome_bin:
        cons.info(f"  Chrome: {chrome_bin}")
        try:
            out, _err, code = run_cmd([str(chrome_bin), "--version"], timeout=30)
        except (PermissionError, OSError) as exc:
            cons.error(
                f"  Chrome binary not executable ({exc.__class__.__name__}); "
                f"re-run install-browser to restore permissions"
            )
            errors += 1
        else:
            if code == 0 and out.strip():
                cons.raw(f"    {out.strip()}")
            else:
                cons.error(f"  Chrome --version failed (exit {code})")
                errors += 1
    else:
        cons.error("  Chrome binary not found")
        errors += 1

    if which("agent-browser"):
        out, _err, _code = run_cmd(["agent-browser", "--version"], timeout=30)
        cons.info(f"  agent-browser: {out.strip() or 'installed'}")
    else:
        cons.error("  agent-browser binary not found")
        errors += 1

    if errors:
        cons.error(f"{errors} check(s) failed")
        return 1
    cons.info("Browser setup complete!")
    return 0


def main(argv: list[str] | None = None) -> int:
    install_sigpipe_handler()
    parser = argparse.ArgumentParser(prog="install-browser", description=__doc__)
    add_common_args(parser)
    args = parser.parse_args(argv)
    cons = console_from_args(args)

    cons.info(f"Browser install script starting (container={is_container()})")
    if install_chrome(cons) != 0:
        return 1
    if install_agent_browser(cons) != 0:
        return 1
    return verify_installation(cons)


if __name__ == "__main__":
    raise SystemExit(main())
