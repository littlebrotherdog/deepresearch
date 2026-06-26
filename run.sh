#!/bin/bash
# Deep Research Agent - Run script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="/ssd1/gengbiao01/python-3.12.13/python/bin:$PATH"

# Prefer project venv if present (local dev), else fall back to server python / system python3
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  PYTHON="python3"
fi

# --- Proxy for Baidu search (external network) ---
export DR_SEARCH_PROXY="${DR_SEARCH_PROXY:-http://amu_2026:amu_2026_test@10.61.124.44:8600}"

# --- Default model config (can be overridden via env or UI) ---
export DR_MODEL_BASE_URL="${DR_MODEL_BASE_URL:-http://amu.dbh.baidu-int.com/v1}"
export DR_MODEL_API_KEY="${DR_MODEL_API_KEY:-sk-oXC9rgXuXSKLuSA5JFZF0pE62adTWEipF5dHv9la2u6SFYQm}"
export DR_MODEL_NAME="${DR_MODEL_NAME:-deepseek-v3.1}"
export DR_HOST="${DR_HOST:-0.0.0.0}"
export DR_PORT="${DR_PORT:-7860}"

echo "============================================"
echo "  Deep Research Agent"
echo "============================================"
echo "  Server:  http://$DR_HOST:$DR_PORT"
echo "  Model:   $DR_MODEL_NAME @ $DR_MODEL_BASE_URL"
echo "  Proxy:   $DR_SEARCH_PROXY"
echo "============================================"
echo ""

exec "$PYTHON" -m api.server
