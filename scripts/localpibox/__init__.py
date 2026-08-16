"""lpb-stack — shared helpers for lpbox Devstack tools.

Small, stdlib-only package that consolidates the common parts that used to
live in shell scripts (support/_lib.sh) and were copy-pasted across tools:

  env  — KEY=VALUE .env/.conf parsing, ${NAME} expansion, layered loading
  log  — colored console output (info/warn/error/done/debug)
  run  — subprocess helpers, tool discovery, container detection
  cli  — argument-parser helpers, prompts, fatal-error exit
"""

from .env import (
    expand_refs,
    find_env_file,
    load_env_chain,
    parse_env_file,
    parse_env_line,
)
from .log import Console, console, debug, done, error, info, warn
from .run import is_container, require, run_cmd, which

__version__ = "0.1.0"

__all__ = [
    "Console",
    "console",
    "debug",
    "done",
    "env",
    "error",
    "expand_refs",
    "find_env_file",
    "info",
    "is_container",
    "load_env_chain",
    "parse_env_file",
    "parse_env_line",
    "require",
    "run_cmd",
    "warn",
    "which",
    "__version__",
]
