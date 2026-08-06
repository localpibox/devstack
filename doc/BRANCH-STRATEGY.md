# LocalPibox Branch Strategy & Versioning

## Overview

The LocalPibox project uses a `lpb` branch on all 5 repositories as the stable integration point. All feature work branches from `lpb` and merges back via PR. The CI pipeline builds from `lpb` only.

## Versioning

Stack version is tracked in `VERSION` files across all repos (source of truth: `config/VERSION`).

**Format:** `v0.X.0-lpb` (SemVer-compatible, `-lpb` suffix distinguishes from upstream pi versions)

- `v0.1.0-lpb` — first stack release
- `v0.2.0-lpb` — next major release
- `v0.2.1-lpb` — patch to v0.2.0-lpb
- `v0.2.1-lpb-dev` — work-in-progress (not finalized)

## Branch Model

```
lpb (stable base for all repos)
├── feat/qwen-reasoning           (feature branch → merge back to lpb)
├── fix/batch-consolidation       (fix branch → merge back to lpb)
├── fix/exa-mcp-tools             (fix branch → merge back to lpb)
└── experimental/...              (experimental → not merged yet)
```

## Repositories

| Repo | Role | lpb Source | Stack Version Location |
|------|------|-----------|----------------------|
| `pi` | Core (forked & patched) | `50e24690` | N/A (has own v0.83.0 tag) |
| `devstack` | Docker image builds | `main` HEAD | `.github/workflows/build-and-publish.yml` |
| `config` | Settings, skills, agents | `main` HEAD | `config/VERSION` |
| `lemonade-pi-plugin` | LLM provider extension | `main` HEAD | `VERSION` |
| `pi-hermes-memory` | Memory extension | `main` HEAD | `VERSION` |

## CI Behavior

devstack CI on `main` branch:
1. Checks out `lpb` from config repo
2. Reads `VERSION` file
3. Clones pi repo from `lpb` branch
4. Builds image tagged as `ghcr.io/localpibox/devstack:<version>-cli` (and `...-web`)

## Bumping Version

To release a new stack version:
1. Merge all tested feature branches into `lpb` on all repos
2. Update `config/VERSION` to new version (e.g., `v0.2.0-lpb`)
3. Update `VERSION` in other repos to match
4. Commit and push to `lpb` on all repos
5. CI triggers and builds with new tags

## Configuration References

In `settings.json` (config repo), extension refs use git branch references:
```json
{
  "packages": [
    "git:github.com/localpibox/lemonade-pi-plugin@lpb",
    "git:github.com/localpibox/pi-hermes-memory@lpb"
  ]
}
```

At runtime, `pi update --extensions` clones these branches. To pin to a specific version for stability, update to:
```json
"git:github.com/localpibox/lemonade-pi-plugin@v0.2.0-lpb"
```
