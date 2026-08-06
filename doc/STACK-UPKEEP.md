# Stack Upkeep — Historical Note

This directory has been removed. The `stack.sh` wrapper and its associated
scripts (`update.sh`, `validate-status.sh`, `check-updates.sh`, `dep-check.sh`,
`apply-patches.sh`) were all part of the old maintenance pattern.

## What replaced it

- **Extension updates**: `podman exec -it localpibox pi update --extensions`
- **Version config**: `versions.env` at the repo root
- **Builder**: `lpb` (container launcher) + direct `podman build` when needed
- **Docs**: This file (`doc/STACK-UPKEEP.md`)

## Original commands (no longer available)

```bash
./stack.sh check       # replaced by reading versions.env
./stack.sh status      # removed — no standalone validator
./stack.sh build       # replaced by `podman build -t ... .`
./stack.sh update      # replaced by `pi update --extensions`
```
