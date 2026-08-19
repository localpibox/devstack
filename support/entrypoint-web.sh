#!/usr/bin/env bash
# /opt/devstack/entrypoint-web.sh — Container entrypoint for Web (VSCodium) image
#
# Thin wrapper that delegates to start.sh for all logic.
# start.sh handles: config, .env loading, first-run bootstrap, native modules,
#                   starting VSCodium server, and executing the target command.
#
# Usage:
#   podman run -d --name lpb-stack --network host --userns keep-id \
#     -v /path/to/project:/home/lpb/workspace/<project-name>:Z \
#     ghcr.io/lpb-stack/devstack:latest-web
#
# Environment variables:
#   All LPB_* vars are handled by start.sh

exec /opt/devstack/start.sh run --mode web "$@"
