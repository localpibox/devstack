# Subagent Spawning Pattern — Browser Testing

## Overview

When spawning subagents for browser testing, use the following pattern to ensure isolated sessions and structured JSON output.

## Steps

### 1. Generate a Unique Session ID

```bash
SESSION_ID=$(npx tsx bin/session-uuid.ts "${PI_WORKTREE_ID}-<test-name>")
```

Example output: `pi-main-abc123-login-flow-7f3a9b2c`

### 2. Load the System Prompt Template

```bash
PROMPT=$(cat subagent-browser-prompt.txt)
```

The template at `subagent-browser-prompt.txt` includes:
- The JSON schema the subagent must produce
- Instructions for using agent-browser with bundled Chrome
- Metrics collection steps (vitals, a11y, snapshot)

### 3. Spawn the Subagent

```javascript
// Via the subagent tool in Pi:
subagent({
  agent: "researcher",
  task: `Run browser test on https://example.com:
    1. Navigate to the URL
    2. Verify the page loads correctly
    3. Check for accessibility issues
    4. Measure performance metrics
    
    Session ID: ${SESSION_ID}
    Prompt: ${PROMPT}`,
  outputSchema: JSON.parse(readFileSync("subagent-browser-schema.json")),
});
```

### 4. Collect and Validate the Result

```bash
# Pipe subagent output to the validator
echo "${SUBAGENT_OUTPUT}" | npx tsx bin/validate-subagent-output.ts

# Close the browser session to prevent zombie processes
agent-browser --session "$SESSION_ID" close
```

### 5. Retry on Failure (Max 3 Attempts)

```typescript
import { validate, buildRepairPrompt } from "./bin/validate-subagent-output";

let output = await spawnSubagent(task);
let result = validate(output);
let attempts = 1;

while (!result.success && attempts < 3) {
  const repairPrompt = buildRepairPrompt(result.error!, originalTask);
  output = await spawnSubagent(repairPrompt);
  result = validate(output);
  attempts++;
}

if (!result.success) {
  console.error(`Test failed after ${attempts} attempts: ${result.error}`);
}
```

## Key Points

- **Always use bundled Chrome** (not CDP) for subagents
- **Always set `AGENT_BROWSER_SESSION`** to a unique value
- **Always pass the JSON schema** in the subagent's prompt
- **Always validate** the output on the parent side
- **Always retry** with a repair prompt if validation fails
- **Cap at 3 attempts** to avoid infinite loops

## File Reference

| File | Purpose |
|------|---------|
| `bin/session-uuid.ts` | Generate unique session IDs |
| `subagent-browser-schema.json` | JSON schema for subagent results |
| `subagent-browser-prompt.txt` | System prompt template |
| `bin/validate-subagent-output.ts` | Parent-side validation utility |
