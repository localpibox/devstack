# LocalPibox Branch Strategy & Versioning

## Overview

LocalPibox uses a **two-tier branch convention**:

- **Own / independent repos** — `main` is the stable integration point
  (devstack, config, localpibox, localpibox.github.io, lpb-memory).
- **Forks of upstream projects** — a dedicated `lpb` branch carries the
  LocalPibox patch on top of upstream; `main`/`master` tracks upstream as much
  as needed for rebase. The CI builds from `main` on devstack.

| Repo | Kind | Stable branch |
|------|------|---------------|
| devstack | own | `main` |
| config | own | `main` |
| localpibox | own | `main` |
| localpibox.github.io | own | `main` |
| lpb-memory | independent (refactored) | `main` |
| pi | fork of `earendil-works/pi` | `lpb` |
| lemonade-pi-plugin | fork of `lemonade-sdk/…` | `lpb` |
| pi-subagents | fork of `tintinweb/…` | `lpb` (hence `@lpb` refs) |

Forks carry all LocalPibox work as a **single squashed commit** on `lpb`; `main`
/`master` is the upstream default branch used for rebasing.

## Versioning

Stack version is tracked in `VERSION` files across repos; **`config/VERSION`
is the source of truth** (CI reads it to tag images). The devstack workflow
does **not** read a `VERSION` in devstack itself — it fetches it from the
config repo reference.

**Format:** `v0.X.0-lpb` (SemVer-compatible, `-lpb` suffix distinguishes from
upstream pi versions). `VERSION` files store the value **without** the leading
`v` (e.g. `0.2.0-lpb`).

Current version: **`0.2.0-lpb`**

## Branch & CI Behavior

devstack CI on `main`:

1. Sources `lpb.stack.env` for fork URLs and refs.
2. Reads config repo `VERSION` (via `raw.githubusercontent.com`).
3. Clones `localpibox/pi` from the `lpb` branch.
4. Builds images tagged as `ghcr.io/localpibox/devstack:<version>-cli` and
   `...-web` (and `latest`/`main-*`/`<sha>-*`).

## Bumping Version

To release a new stack version:

1. Merge all tested feature branches into the stable branch of each repo.
2. Update `config/VERSION` to the new version (e.g. `0.2.1-lpb`).
3. Update `VERSION` in devstack, lpb-memory, lemonade-pi-plugin to match.
4. Commit and push on the stable branch of each repo.
5. CI triggers and rebuilds with the new tags.

## Configuration References

In `settings.json` (config repo), extension refs use git branch references
matching each repo's actual branch:

```json
{
  "packages": [
    "git:github.com/localpibox/lemonade-pi-plugin@lpb",
    "git:github.com/localpibox/lpb-memory@main",
    "git:github.com/localpibox/pi-subagents@lpb"
  ]
}
```

At runtime, `pi update --extensions` clones these branches. To pin to a
specific version for stability, update to e.g.:
`"git:github.com/localpibox/lemonade-pi-plugin@v0.2.0-lpb"`.
