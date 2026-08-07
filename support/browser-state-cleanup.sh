#!/usr/bin/env bash
# browser-state-cleanup.sh — housekeeping for /browser-states/ volume
#
# Run on container start (post-start.sh) or manually.
# Remove sessions older than 7 days OR when count exceeds 20.
# Also kills orphaned Chrome/agent-browser processes.
set -euo pipefail

STATE_DIR="/browser-states"
MAX_AGE_DAYS=7
MAX_COUNT=20

# Kill orphaned agent-browser and Chrome processes
# (sessions should be closed properly, but clean up stragglers)
echo "  Cleaning orphaned browser processes..."
pkill -f "agent-browser" 2>/dev/null || true
pkill -f "chrome.*--headless" 2>/dev/null || true
sleep 1

# Ensure the state directory exists
mkdir -p "$STATE_DIR"

# Age-based cleanup: remove sessions older than 7 days
find "$STATE_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +"$MAX_AGE_DAYS" -exec rm -rf {} + 2>/dev/null || true

# Count-based cleanup: keep only MAX_COUNT most recent
CURRENT=$(find "$STATE_DIR" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
if [ "$CURRENT" -gt "$MAX_COUNT" ]; then
  REMOVE_COUNT=$((CURRENT - MAX_COUNT))
  find "$STATE_DIR" -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
    | sort -n | head -n "$REMOVE_COUNT" | awk '{print $2}' \
    | xargs -r rm -rf
fi

REMAINING=$(ls -1d "$STATE_DIR"/*/ 2>/dev/null | wc -l)
logger -t browser-states "Cleanup complete. Remaining sessions: $REMAINING" 2>/dev/null || \
  echo "browser-states: Cleanup complete. Remaining sessions: $REMAINING"
