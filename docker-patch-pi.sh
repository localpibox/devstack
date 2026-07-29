#!/bin/bash
set -e

echo "=== Patching Pi monorepo with reasoning_effort support ==="

# Clone the localpibox/pi monorepo
REPO_DIR="/opt/pi-fork"
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning localpibox/pi monorepo..."
    git clone --depth=1 https://github.com/localpibox/pi.git "$REPO_DIR"
fi

cd "$REPO_DIR"

# Use sed to add reasoning_effort to Qwen handler
FILE="$REPO_DIR/packages/ai/dist/api/openai-completions.js"

# Patch Qwen branch (add reasoning_effort after enable_thinking line)
sed -i '/compat\.thinkingFormat === "qwen" && model\.reasoning/,/^[[:space:]]*}/{
    /params\.enable_thinking = !!options?.reasoningEffort;$/a\        // Also send reasoning_effort for granularity (high/medium/low)\
        if (options?.reasoningEffort \&\& options.reasoningEffort !== "off") {\
            params.reasoning_effort = model.thinkingLevelMap?.[options.reasoningEffort] ?? options.reasoningEffort;\
        }
}' "$FILE"

# Patch Qwen-chat-template branch
sed -i '/compat\.thinkingFormat === "qwen-chat-template" && model\.reasoning/,/^[[:space:]]*preserve_thinking: true,/{
    /preserve_thinking: true,$/a\        // Also send reasoning_effort in chat template kwargs\
        if (options?.reasoningEffort \&\& options.reasoningEffort !== "off") {\
            params.chat_template_kwargs.reasoning_effort = model.thinkingLevelMap?.[options.reasoningEffort] ?? options.reasoningEffort;\
        }
}' "$FILE"

# Verify the patch
echo ""
echo "Verifying Qwen patch:"
grep -A8 'compat.thinkingFormat === "qwen"' "$FILE" | head -10

echo ""
echo "=== Pi monorepo patched ==="
