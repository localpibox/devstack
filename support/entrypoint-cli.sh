#!/usr/bin/env bash
# /opt/devstack/entrypoint-cli.sh — Container entrypoint for CLI image
#
# Thin wrapper that delegates to start.sh for all logic.
# start.sh handles: config, .env loading, first-run bootstrap, native modules,
#                   and executing the target command.
#
# Usage:
#   podman run -it --network host --userns keep-id \
#     -v /path/to/project:/home/lpb/workspace/<project-name>:Z \
#     ghcr.io/lpb-stack/devstack:latest-cli
#
# Environment variables:
#   All LPB_* vars are handled by start.sh

MODE="${LPB_START_MODE:-cli}"
exec /opt/devstack/start.sh run --mode "$MODE" "$@"
