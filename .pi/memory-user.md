User Preferences (Memory):

1. **Subprocess Model Routing Verification**: User prefers verifying subprocess model routing by having it perform a visible task (tell a story, do computation) so they can watch NPU/monitoring tools to confirm the right model hardware is active, rather than just checking log output. <!-- created=2026-08-15 -->

2. **Configurable Timeouts & Thresholds**: User explicitly stated timeouts should be configurable, not hardcoded — important for fine-tuning operations. This applies to all timeout/threshold values in subprocess invocations (NPU model calls). <!-- created=2026-08-15 -->

3. **Upstream Fixes Over Downstream Workarounds**: Prefers proper root-cause fixes over workarounds/band-aids. Calls out when a solution masks a deeper design problem (e.g., "this was a workaround not a proper solution"). Expects upstream prevention (fix prompts/architecture) rather than downstream filtering (regex patterns, meta-entry cleanup). <!-- created=2026-08-15 -->

4. **lpb-memory NPU Model**: User wants the lpb-memory extension to use the NPU model (a separate model from the main Qwen3.6-35B-A3B-MTP-GGUF session model) for background memory operations. <!-- created=2026-08-15 -->