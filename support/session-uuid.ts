#!/usr/bin/env tsx
/**
 * session-uuid.ts — CLI utility for generating unique session names.
 *
 * Usage: npx tsx bin/session-uuid.ts <prefix>
 * Output: <prefix>-<uuid> (e.g., pi-main-abc123-login-flow-7f3a9b2c)
 *
 * Used by AGENT_BROWSER_SESSION naming convention:
 *   <worktree-id>-<test-name>-<uuid>
 */

import { randomUUID } from "node:crypto";

const prefix = process.argv[2];

if (!prefix) {
  console.error("Usage: npx tsx bin/session-uuid.ts <prefix>");
  process.exit(1);
}

// Generate a short UUID (first 8 hex chars) for readability
const shortUuid = randomUUID().replace(/-/g, "").slice(0, 8);
console.log(`${prefix}-${shortUuid}`);
