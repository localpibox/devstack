"""Stable-release promotion engine (dev branches → stable branches).

Per repo: reset local stable branch to origin/<stable>, merge
origin/<dev> (ff or clean 3-way), push. Unrelated histories (first
release) require --rebase: stable is replaced with the dev history
(force-push). Conflicts leave the repo untouched. devstack only: the
-dev VERSION suffix is stripped on the stable branch and committed.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..cli import confirm
from ..log import Console
from .gitutil import git, git_auth
from .repos import DEFAULT_AGENT_DIR, WORKSPACE_REPOS, WORKSPACE_ROOT
from .version import get_version


def _release_repos() -> list[tuple[str, Path, str, str, str]]:
    """All 6 stack repos: (label, path, dev_branch, main_branch, github_repo)."""
    repos: list[tuple[str, Path, str, str, str]] = []
    for name, _is_sym, _is_ext, dev_branch, main_branch in WORKSPACE_REPOS:
        repos.append((name, WORKSPACE_ROOT / name, dev_branch, main_branch,
                      f"lpb-stack/{name}"))
    repos.append(("config", Path(DEFAULT_AGENT_DIR), "dev", "main",
                  "lpb-stack/config"))
    return repos


def _repo_release_state(path: Path, dev_branch: str, main_branch: str,
                        cons: Console | None = None) -> dict:
    """Fetch and gather per-repo promotion state (non-destructive)."""
    # Explicit refspecs: some clones (e.g. config) have restricted fetch
    # configs that would not create refs/remotes/origin/<dev>.
    if cons is not None:
        cons.info(f"  fetching {path.name} …")
    git_auth(path, "fetch", "origin", "--quiet",
             f"+refs/heads/{dev_branch}:refs/remotes/origin/{dev_branch}",
             f"+refs/heads/{main_branch}:refs/remotes/origin/{main_branch}",
             timeout=180)
    dirty, _, _ = git(path, "status", "--porcelain")
    state: dict = {
        "dirty": bool(dirty.strip()),
        "local_ahead": 0,        # local stable commits not on origin
        "origin_dev": "?",
        "origin_main": "?",
        "main_behind_by": None,   # commits on dev not on main (None = unknown)
        "diverged": False,        # main has commits not on dev
        "feasibility": "unknown", # aligned|ahead|ff|merge|conflict|unrelated
    }
    out, _, code = git(path, "rev-parse", "--verify", f"origin/{dev_branch}")
    if code == 0:
        state["origin_dev"] = out.strip()[:8]
    out, _, code = git(path, "rev-parse", "--verify", f"origin/{main_branch}")
    if code == 0:
        state["origin_main"] = out.strip()[:8]
        out, _, code = git(path, "rev-list", "--count",
                           f"origin/{main_branch}..{main_branch}")
        if code == 0:
            state["local_ahead"] = int(out.strip())
    if state["origin_dev"] != "?" and state["origin_main"] != "?":
        _, _, code = git(path, "merge-base",
                         f"origin/{main_branch}", f"origin/{dev_branch}")
        if code != 0:
            state["feasibility"] = "unrelated"
        else:
            out, _, code = git(path, "rev-list", "--count",
                               f"origin/{main_branch}..origin/{dev_branch}")
            if code == 0:
                state["main_behind_by"] = int(out.strip())
            out, _, code = git(path, "rev-list", "--count",
                               f"origin/{dev_branch}..origin/{main_branch}")
            if code == 0 and int(out.strip()) > 0:
                state["diverged"] = True
            if state["main_behind_by"] == 0:
                state["feasibility"] = "ahead" if state["diverged"] else "aligned"
            elif state["diverged"]:
                _, _, code = git(path, "merge-tree", "--write-tree",
                                 f"origin/{main_branch}", f"origin/{dev_branch}")
                state["feasibility"] = "merge" if code == 0 else "conflict"
            else:
                state["feasibility"] = "ff"
    return state


def _repo_action(st: dict, rebase: bool) -> tuple[str, str | None]:
    """Decide the promotion action for a repo: (action, skip_reason)."""
    if st["feasibility"] == "unknown":
        return "unknown", "origin refs not found — check repo/remote"
    if st["feasibility"] == "aligned":
        return "no-op", None
    if st["feasibility"] == "ahead":
        return "no-op", ("stable is AHEAD of dev — verify stable's unique "
                         "commits before promoting")
    if st["local_ahead"] > 0:
        return "skip", (f"local stable branch has {st['local_ahead']} unpushed "
                       f"commit(s) — git branch -D <stable> first, then re-run")
    if st["dirty"]:
        return "skip", "local uncommitted changes (commit/stash first)"
    if st["feasibility"] == "conflict":
        return "conflict", "merge conflict — resolve manually"
    if st["feasibility"] == "unrelated":
        if rebase:
            return "rebase", None
        return "unrelated", ("unrelated histories — re-run with --rebase "
                             "(replaces stable with dev history, force-push)")
    return st["feasibility"], None  # ff | merge


def _set_commit_author() -> None:
    """Force LocalPibox author identity for git commits made by this process."""
    os.environ["GIT_AUTHOR_NAME"] = "localpibox"
    os.environ["GIT_AUTHOR_EMAIL"] = "localpibox@gmail.com"
    os.environ["GIT_COMMITTER_NAME"] = "localpibox"
    os.environ["GIT_COMMITTER_EMAIL"] = "localpibox@gmail.com"


def cmd_release_status(cons: Console) -> int:
    """Show stable-release readiness across all 6 stack repos."""
    version = get_version()
    cons.info(f"devstack VERSION: {version}  (pipeline: "
              f"{'dev' if '-dev' in version else 'main'})")
    cons.info("")
    problems = 0
    for label, path, dev_b, main_b, gh in _release_repos():
        if not path.is_dir():
            cons.error(f"{label:18s} repo missing at {path}")
            problems += 1
            continue
        st = _repo_release_state(path, dev_b, main_b, cons)
        feas = st["feasibility"]
        if feas == "unknown":
            mark, note = "❌", "origin refs not found (fetch failed?)"
            problems += 1
        elif feas == "aligned":
            mark, note = "✅", "aligned"
        elif feas == "ahead":
            mark, note = "⚠️", f"{main_b} is AHEAD of dev — check its unique commits"
            problems += 1
        elif feas == "ff":
            mark, note = "✅", f"{main_b} {st['main_behind_by']} behind → fast-forward"
        elif feas == "merge":
            mark, note = "✅", f"{main_b} {st['main_behind_by']} behind → clean 3-way merge"
        elif feas == "conflict":
            mark, note = "⚠️", "merge conflict — resolve manually"
            problems += 1
        else:  # unrelated
            mark, note = "⚠️", ("unrelated histories → promote --rebase "
                                "(replaces history, force-push)")
            problems += 1
        if st["dirty"]:
            note += "; LOCAL DIRTY (uncommitted changes will not be promoted)"
            problems += 1
        if st["local_ahead"] > 0:
            note += (f"; LOCAL {main_b} AHEAD ({st['local_ahead']} unpushed "
                     f"commit(s) — delete local branch to promote)")
            problems += 1
        cons.info(f"{mark} {label:18s} {gh}")
        cons.info(f"     {dev_b}={st['origin_dev']}  {main_b}={st['origin_main']}  {note}")
    cons.info("")
    if problems:
        cons.warn(f"{problems} issue(s) — see above before promoting.")
    else:
        cons.done("All repos ready for stable promotion.")
    return 0


def cmd_release_promote(*, assume_yes: bool, dry_run: bool, rebase: bool,
                        cons: Console) -> int:
    """Promote dev branches to stable branches across all 6 stack repos.

    Per repo (merge ff or clean 3-way): reset local stable branch to origin,
    merge origin/<dev>. Unrelated histories (re-initialized stable branch):
    with --rebase, replace stable with the dev history (force-push) — the
    first-release mode. On conflict: leave the repo untouched, report.
    devstack only: strip the -dev VERSION suffix on the stable branch.
    Then push all successfully promoted repos. CI (main pipeline) then
    builds/tags once VERSION changes on main (manual tagging — CI never
    bumps; if main's VERSION already matches, re-tag with
    `lpb-devstack tag-repos --branch main`).
    """
    _set_commit_author()
    version = get_version()
    if "-dev" not in version:
        cons.warn(f"local devstack VERSION={version} has no -dev suffix — "
                  "run 'git pull --ff-only' on dev first if possible.")

    # ── Pre-flight ──
    entries: list[tuple[str, Path, str, str, str, dict]] = []
    ok = True
    for label, path, dev_b, main_b, gh in _release_repos():
        if not path.is_dir():
            cons.error(f"{label}: repo missing at {path}")
            ok = False
            continue
        st = _repo_release_state(path, dev_b, main_b, cons)
        entries.append((label, path, dev_b, main_b, gh, st))
        if st["origin_main"] == "?":
            cons.error(f"{label}: origin/{main_b} does not exist")
            ok = False
    if not ok:
        cons.error("Pre-flight failed — aborting, nothing was changed.")
        return 1

    cons.info("")
    cons.info("Stable release plan:")
    for label, _p, dev_b, main_b, gh, st in entries:
        action, skip_reason = _repo_action(st, rebase)
        if skip_reason:
            cons.warn(f"  {gh}: SKIP — {skip_reason}")
        else:
            cons.info(f"  {gh}: {action} (origin/{dev_b} → {main_b})")
    cons.info("  devstack: strip -dev from VERSION on main")
    if dry_run:
        cons.info("")
        cons.info("Dry run — nothing was changed.")
        return 0
    cons.info("")
    if rebase:
        rebased_plan = [gh for _l, _p, _db, _mb, gh, st in entries
                        if _repo_action(st, rebase)[0] == "rebase"]
        msg = (f"Promote to stable branches and push? "
               f"(FORCE-PUSH on: {', '.join(rebased_plan)})")
    else:
        msg = "Promote to stable branches and push?"
    if not assume_yes and not confirm(msg):
        cons.info("Aborted.")
        return 1

    # ── Merge ──
    failures: list[str] = []
    skipped: list[str] = []
    rebased: list[str] = []
    for label, path, dev_b, main_b, gh, st in entries:
        cons.info(f"── {label} ──")
        action, skip_reason = _repo_action(st, rebase)
        if skip_reason:
            cons.warn(f"  {label}: {skip_reason}")
            skipped.append(label)
            continue
        if action == "no-op":
            cons.info(f"  {label}: already aligned — nothing to do")
            continue
        if action == "rebase":
            out, err, code = git(path, "checkout", "-q", "-B", main_b,
                                 f"origin/{dev_b}")
            if code != 0:
                cons.error(f"  {label}: rebase checkout failed: "
                           f"{err.strip() or out.strip()}")
                failures.append(label)
                continue
            rebased.append(label)
            cons.info(f"  {label}: {main_b} reset to origin/{dev_b} "
                      f"(first-release mode, will force-push)")
            continue
        # ff / merge
        out, err, code = git(path, "checkout", "-q", "-B", main_b, f"origin/{main_b}")
        if code != 0:
            cons.error(f"  {label}: checkout {main_b} failed: {err.strip() or out.strip()}")
            failures.append(label)
            continue
        out, err, code = git(path, "merge", "--no-edit", f"origin/{dev_b}")
        if code != 0:
            git(path, "merge", "--abort")
            git(path, "reset", "-q", "--hard", f"origin/{main_b}")
            cons.error(f"  {label}: MERGE CONFLICT — {main_b} left untouched, "
                       "resolve manually")
            failures.append(label)
            continue
        if "up to date" in (out + err):
            cons.info(f"  {label}: already up to date")
        else:
            cons.info(f"  {label}: merged origin/{dev_b} → {main_b} ({action})")

    # ── devstack VERSION: strip -dev on main ──
    for label, path, dev_b, main_b, gh, st in entries:
        if label != "devstack" or label in failures or label in skipped:
            continue
        vf = path / "VERSION"
        current = vf.read_text().strip()
        if current.endswith("-dev"):
            stable = current[: -len("-dev")]
            vf.write_text(stable + "\n")
            git(path, "add", "VERSION")
            cons.info(f"  devstack: committing VERSION {current} → {stable} "
                      f"on {main_b} …")
            cons.info("  (pre-commit hook runs the test suite — may take a "
                      "while)")
            out, err, code = git(path, "commit", "-m",
                                 f"release: {stable} — stable branch promoted "
                                 f"from dev",
                                 timeout=600)
            if code != 0:
                detail = err.strip() or out.strip() or "unknown error"
                cons.error(f"  devstack: VERSION commit failed: {detail}")
                cons.error("  State: main has the merged dev content; the "
                           "VERSION change is STAGED (not committed).")
                cons.error(
                    f"  Recover: cd {path} && "
                    f"git commit -m 'release: {stable} — stable branch promoted "
                    f"from dev' && git push origin {main_b}"
                )
                failures.append("devstack")
            else:
                cons.info(f"  devstack: VERSION {current} → {stable} (on {main_b})")

    # ── Push ──
    cons.info("")
    cons.info("Pushing stable branches...")
    for label, path, dev_b, main_b, gh, st in entries:
        if label in failures or label in skipped:
            continue
        action, _ = _repo_action(st, rebase)
        if action == "no-op":
            continue
        push_args = ["push", "origin", main_b]
        if label in rebased:
            push_args = ["push", "--force-with-lease", "origin", main_b]
        cons.info(f"  pushing {gh}:{main_b} …")
        out, err, code = git_auth(path, *push_args, timeout=180)
        if code != 0:
            cons.error(f"  {label}: push failed: {err.strip() or out.strip()}")
            failures.append(label)
        else:
            force = " (force)" if label in rebased else ""
            cons.info(f"  pushed {gh}:{main_b}{force}")

    # ── Summary ──
    cons.info("")
    cons.info("Result:")
    for label, path, dev_b, main_b, gh, st in entries:
        if label in failures:
            cons.error(f"  ❌ {gh:35s} failed")
        elif label in skipped:
            cons.warn(f"  ⏭ {gh:35s} skipped")
        elif _repo_action(st, rebase)[0] == "no-op":
            cons.info(f"  ✅ {gh:35s} aligned (no change)")
        else:
            force = " (force)" if label in rebased else ""
            cons.info(f"  ✅ {gh:35s} promoted{force}")
    if skipped:
        cons.warn(f"Skipped: {', '.join(skipped)} — see notes above")
    if failures:
        cons.error(f"Failed: {', '.join(failures)}")
        cons.error("Stable release INCOMPLETE — complete the failing repo "
                   "(recovery steps above), then re-run "
                   "'lpb-devstack release promote' (already-promoted repos "
                   "fast-forward or no-op).")
        return 1
    stable_version = (version[:-len("-dev")] if version.endswith("-dev") else version)
    cons.done(f"Promoted all 6 repos. main's VERSION is now {stable_version}.")
    cons.info(f"CI (main pipeline) now builds :{stable_version}-* / :main-* / :latest-*")
    cons.info("and tags the 5 repos at the stable branches.")
    cons.info("After CI passes:")
    cons.info("  1. lpb-devstack --tag main workspace sync --extensions")
    cons.info("  2. pi update --extensions")
    cons.info(f"  (If CI's tag-repos didn't run: lpb-devstack tag-repos --branch main --version {stable_version})")
    return 0
