"""localpibox.stack — LocalPibox stack operations library.

Module layout (split from the former single _stack_lib module):

  gitutil   — git helpers (plain + GitHub-auth aware)
  repos     — path constants, 6-repo stack map, tagging repo list
  version   — pipeline detection, VERSION discovery + bump math, stack env
  workspace — workspace sync/clone/ensure + settings.json pin helpers
  validate  — full-stack alignment validation
  release   — stable-release promotion engine (dev → stable)

Import the public API from this package, or from the legacy
``localpibox._stack_lib`` shim (kept for backwards compatibility).
"""

from .gitutil import git, git_auth, git_remote
from .repos import (
    AGENT_GIT,
    DEFAULT_AGENT_DIR,
    DEFAULT_REMOTE,
    DEFAULT_REF,
    EXTENSION_REPOS,
    LPB_EXTENSION_REPOS,
    MIGRATE_KEEP,
    MEMORY_CONFIG_PATH,
    MEMORY_CONFIG_TEMPLATE,
    TAG_REPOS,
    VERSION_RE,
    WORKSPACE_REPOS,
    WORKSPACE_ROOT,
    migrate_legacy_layout,
)
from .version import (
    bump_version,
    detect_pipeline,
    expected_branch,
    get_stack_env,
    get_version,
    parse_version,
)
from .workspace import (
    cmd_workspace_ensure,
    cmd_workspace_status,
    cmd_workspace_sync,
    cmd_workspace_sync_extensions,
)
from .validate import cmd_validate
from .release import cmd_release_promote, cmd_release_status

__all__ = [
    "AGENT_GIT",
    "DEFAULT_AGENT_DIR",
    "DEFAULT_REMOTE",
    "DEFAULT_REF",
    "EXTENSION_REPOS",
    "LPB_EXTENSION_REPOS",
    "MIGRATE_KEEP",
    "MEMORY_CONFIG_PATH",
    "MEMORY_CONFIG_TEMPLATE",
    "TAG_REPOS",
    "VERSION_RE",
    "WORKSPACE_REPOS",
    "WORKSPACE_ROOT",
    "bump_version",
    "cmd_release_promote",
    "cmd_release_status",
    "cmd_validate",
    "cmd_workspace_ensure",
    "cmd_workspace_status",
    "cmd_workspace_sync",
    "cmd_workspace_sync_extensions",
    "detect_pipeline",
    "expected_branch",
    "get_stack_env",
    "get_version",
    "git",
    "git_auth",
    "git_remote",
    "migrate_legacy_layout",
    "parse_version",
]
