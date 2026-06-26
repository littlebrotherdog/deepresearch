#!/bin/bash
# Deep Research Agent - Run script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer project venv if present (local dev), else fall back to system python
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  PYTHON="python3"
fi

# --- Proxy for search engines (set via env or UI) ---
# export DR_SEARCH_PROXY="http://user:pass@proxy-host:port"

# --- Default model config (set via env or UI) ---
# export DR_MODEL_BASE_URL="http://your-llm-api-host/v1"
# export DR_MODEL_API_KEY="sk-your-api-key"
export DR_MODEL_NAME="${DR_MODEL_NAME:-deepseek-v3.1}"
export DR_HOST="${DR_HOST:-0.0.0.0}"
export DR_PORT="${DR_PORT:-7860}"

echo "============================================"
echo "  Deep Research Agent"
echo "============================================"
echo "  Server:  http://$DR_HOST:$DR_PORT"
echo "  Model:   $DR_MODEL_NAME"
echo "============================================"
echo ""

exec "$PYTHON" -m api.server
