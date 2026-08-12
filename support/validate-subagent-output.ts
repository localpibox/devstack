#!/usr/bin/env tsx

/**
 * validate-subagent-output.ts — Parent-side JSON validation + retry utility
 *
 * Validates subagent output against the browser test result schema.
 * Cleans raw text (removes markdown fences, preamble), parses JSON,
 * and validates with Zod. Returns the validated result or an error.
 *
 * Usage:
 *   echo '<raw subagent output>' | npx tsx bin/validate-subagent-output.ts [--schema <path>]
 *   npx tsx bin/validate-subagent-output.ts <raw-output>
 */

import { z } from "zod";

// ─── Schema ──────────────────────────────────────────────────────────────────

const SubagentResultSchema = z.object({
  url: z.string(),
  status: z.enum(["PASS", "WARN", "FAIL"]),
  testName: z.string().optional(),
  checks: z.array(
    z.object({
      check: z.string(),
      description: z.string().optional(),
      pass: z.boolean(),
      evidence: z.string().optional(),
    }),
  ),
  metrics: z
    .object({
      lcp_ms: z.number().optional(),
      cls: z.number().optional(),
      ttfb_ms: z.number().optional(),
      inp_ms: z.number().optional(),
      a11y_violations: z.number().optional(),
      a11y_passes: z.number().optional(),
    })
    .optional(),
  error: z.string().optional(),
  session_id: z.string().optional(),
});

type SubagentResult = z.infer<typeof SubagentResultSchema>;

// ─── JSON Cleaning ───────────────────────────────────────────────────────────

function cleanJsonOutput(raw: string): string {
  // Remove markdown code fences
  let cleaned = raw.replace(/```(?:json)?\s*/g, "").replace(/```/g, "");
  // Remove preamble text before the first {
  const firstBrace = cleaned.indexOf("{");
  if (firstBrace > 0) {
    cleaned = cleaned.slice(firstBrace);
  }
  // Remove trailing text after the last }
  const lastBrace = cleaned.lastIndexOf("}");
  if (lastBrace < cleaned.length - 1) {
    cleaned = cleaned.slice(0, lastBrace + 1);
  }
  return cleaned.trim();
}

// ─── Validation ──────────────────────────────────────────────────────────────

function validate(
  raw: string,
  _schemaPath?: string,
): { success: boolean; data?: SubagentResult; error?: string } {
  const cleaned = cleanJsonOutput(raw);

  try {
    const parsed = JSON.parse(cleaned);

    // If a custom schema path is provided, load it (for future extensibility)
    // For now, use the built-in schema
    const result = SubagentResultSchema.safeParse(parsed);
    if (!result.success) {
      const details = result.error.errors
        .map(e => `${e.path.join(".") || "root"}: ${e.message}`)
        .join("; ");
      return { success: false, error: `Schema validation failed: ${details}` };
    }
    return { success: true, data: result.data };
  } catch (e) {
    return {
      success: false,
      error: `JSON parse error: ${e instanceof Error ? e.message : String(e)}`,
    };
  }
}

// ─── Build Repair Prompt ─────────────────────────────────────────────────────

function buildRepairPrompt(error: string, originalPrompt?: string): string {
  const base =
    originalPrompt ?? "Run the browser test and return structured JSON output.";

  return `${base}

## Previous Validation Error
${error}

Please fix the JSON output and return valid JSON matching the schema.
Remember: return ONLY valid JSON. No preamble. No markdown formatting.`;
}

// ─── Main ────────────────────────────────────────────────────────────────────

function main(): void {
  const args = process.argv.slice(2);
  let raw: string;

  // Check if input comes from stdin (no arguments and stdin is a pipe)
  if (args.length === 0 && process.stdin.isTTY === false) {
    const chunks: Buffer[] = [];
    process.stdin.on("data", (chunk: Buffer) => chunks.push(chunk));
    process.stdin.on("end", () => {
      raw = Buffer.concat(chunks).toString();
      run(raw);
    });
    return;
  }

  // Otherwise read from argument
  const schemaPath = args.find((a, i) => a === "--schema" && args[i + 1])
    ? args[args.indexOf("--schema") + 1]
    : undefined;

  raw = args.filter(a => !a.startsWith("--")).join(" ");

  if (!raw) {
    console.error(
      "Usage: echo '<output>' | npx tsx bin/validate-subagent-output.ts [--schema <path>]",
    );
    console.error(
      "       npx tsx bin/validate-subagent-output.ts '<raw output>'",
    );
    process.exit(1);
  }

  run(raw, schemaPath);
}

function run(raw: string, _schemaPath?: string): void {
  const result = validate(raw, _schemaPath);

  if (result.success) {
    console.log("✓ Valid subagent output");
    console.log(JSON.stringify(result.data, null, 2));
    process.exit(0);
  } else {
    console.error(`✗ Invalid subagent output: ${result.error}`);
    const repairPrompt = buildRepairPrompt(result.error!);
    console.error("\nRepair prompt (use this to re-prompt the subagent):");
    console.error(repairPrompt);
    process.exit(1);
  }
}

// Export for programmatic use
export { buildRepairPrompt, cleanJsonOutput, SubagentResultSchema, validate };

// Run if called directly
if (typeof require !== "undefined" && require.main === module) {
  main();
} else if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
