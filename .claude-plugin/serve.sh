#!/bin/sh
set -eu

ROOT="${CLAUDE_PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
VENV="$ROOT/.venv-plugin"

if [ ! -x "$VENV/bin/axon" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON=python3
    else
        PYTHON=python
    fi

    "$PYTHON" -m venv "$VENV" >&2
    "$VENV/bin/pip" install --quiet --disable-pip-version-check -e "$ROOT" 1>&2
fi

exec "$VENV/bin/axon" serve
