#!/bin/sh
set -eu

ROOT="${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-${PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}}}"
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    PYTHON=python
fi

cd "$ROOT"
PYTHONPATH="$ROOT/src" exec "$PYTHON" -S -m axon.mcp_stdio
