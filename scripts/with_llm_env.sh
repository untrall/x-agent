#!/usr/bin/env bash
# Run a command with the chat-model environment (LLM_BASE_URL / LLM_MODEL /
# LLM_API_KEY). The key comes from macOS Keychain (service x-agent-llm)
# unless LLM_API_KEY is already exported; it is never printed or written
# to disk, and never appears in command-line arguments.
#
# Store the key once (prompts, no echo):
#   security add-generic-password -a "$USER" -s x-agent-llm -w
#
#   bash scripts/with_llm_env.sh .venv/bin/python scripts/run_agent.py ... --chat-model
set -euo pipefail

export LLM_BASE_URL="${LLM_BASE_URL:-https://sem.ensureok.ai/v1}"
export LLM_MODEL="${LLM_MODEL:-glm-5.2}"
if [ -z "${LLM_API_KEY:-}" ]; then
  # Either Keychain service name works (semantix-xagent is the team's name).
  for service in x-agent-llm semantix-xagent; do
    LLM_API_KEY=$(security find-generic-password -a "$USER" -s "$service" -w 2>/dev/null) && break
  done
  if [ -z "${LLM_API_KEY:-}" ]; then
    echo "没找到模型密钥。先运行一次：security add-generic-password -a \"\$USER\" -s x-agent-llm -w" >&2
    exit 1
  fi
  export LLM_API_KEY
fi
exec "$@"
