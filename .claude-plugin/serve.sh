#!/bin/sh
set -eu

ROOT="${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}}"
if [ -n "${AXON_PLUGIN_VENV:-}" ]; then
    VENV="$AXON_PLUGIN_VENV"
else
    CACHE_ROOT="${XDG_CACHE_HOME:-${TMPDIR:-/tmp}}"
    ROOT_KEY="$(printf '%s' "$ROOT" | cksum | awk '{print $1}')"
    VENV="${CACHE_ROOT%/}/axon-plugin-venv-$ROOT_KEY"
fi

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
