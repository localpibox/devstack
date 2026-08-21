"""localpibox._stack_lib — compatibility shim.

The stack library moved to the ``localpibox.stack`` package
(gitutil / repos / version / workspace / validate / release). This shim
re-exports everything so existing imports keep working unchanged:

  from localpibox import _stack_lib as sl
  from localpibox._stack_lib import git, detect_pipeline, ...

New code should import from ``localpibox.stack`` directly. Note that
module-level constants live in their owning submodule (repos, version,
workspace) — mock.patch targets must use the owning module, not this shim.
"""

from __future__ import annotations

from .stack import (  # noqa: F401
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
    bump_version,
    cmd_release_promote,
    cmd_release_status,
    cmd_validate,
    cmd_workspace_ensure,
    cmd_workspace_status,
    cmd_workspace_sync,
    cmd_workspace_sync_extensions,
    detect_pipeline,
    expected_branch,
    get_stack_env,
    get_version,
    git,
    git_auth,
    git_remote,
    migrate_legacy_layout,
    parse_version,
)
from .stack.gitutil import _github_token, _git_authenticated  # noqa: F401
from .stack.repos import _repo_remote  # noqa: F401
from .stack.version import _find_version_file  # noqa: F401
from .stack.workspace import (  # noqa: F401
    _clone_repo,
    _detached_ref,
    _ensure_branch_tracked,
    _get_pinned_versions,
    _is_dirty,
    _read_settings,
    _repo_branch,
    _repo_head,
    _resolve_repo_path,
    _sync_repo,
    _update_pinned_versions,
    _write_settings,
)
