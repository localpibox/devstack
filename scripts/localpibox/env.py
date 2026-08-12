"""KEY=VALUE environment-file parsing and loading.

Replaces the shell `parse_env_file` from `support/_lib.sh` and the
`_parse_env_file` re-implementation in `scripts/lpb.py`, so a single
implementation is shared by every LocalPibox tool.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_LINE_RE = re.compile(r"^\s*(?:(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*))\s*=\s*(.*)$")
_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_env_line(line: str) -> tuple[str | None, str]:
    """Parse a single ``KEY=VALUE`` line -> ``(key, value)``.

    Returns ``(None, "")`` for comment, blank, or non-assignment lines.
    Handles an optional ``export`` prefix, trims surrounding whitespace, and
    strips one layer of matching surrounding quotes from the value.
    """
    if not line.strip() or line.lstrip().startswith("#"):
        return None, ""
    m = _LINE_RE.match(line)
    if not m:
        return None, ""
    key, value = m.group(1), m.group(2).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse all ``KEY=VALUE`` lines from *path* into a dict.

    Missing or unreadable files yield ``{}`` (mirrors the shell guard
    ``[[ -f "$file" ]] || return 0`` in ``_lib.sh``).
    """
    env: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                key, value = parse_env_line(line)
                if key is not None:
                    env[key] = value
    except OSError:
        pass
    return env


def expand_refs(value: str, mapping: dict[str, str] | None = None) -> str:
    """Expand ``${NAME}`` references in *value*.

    Lookup order is *mapping* (if given) then the process environment;
    unset names expand to ``""`` (bash ``source`` semantics for unset vars).
    """
    mapping = mapping or {}
    return _REF_RE.sub(lambda m: mapping.get(m.group(1), os.environ.get(m.group(1), "")), value)


def load_env_chain(
    paths: list[str | Path],
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Parse files in order, each layer overriding the previous.

    ``${NAME}`` references in later files are expanded against the values
    accumulated so far, then *environ* (default: ``os.environ``). This mirrors
    the ``set -a; source a.env; source b.env`` behaviour of the shell tools.
    """
    environ = os.environ if environ is None else environ
    merged: dict[str, str] = {}

    def _sub(m: re.Match[str]) -> str:
        return merged.get(m.group(1), environ.get(m.group(1), ""))

    for p in paths:
        for key, value in parse_env_file(p).items():
            merged[key] = _REF_RE.sub(_sub, value)
    return merged


def find_env_file(name: str, *search_dirs: str | Path) -> Path | None:
    """Return the first existing *name* under *search_dirs*, else ``None``."""
    for d in search_dirs:
        candidate = Path(d) / name
        if candidate.is_file():
            return candidate
    return None
