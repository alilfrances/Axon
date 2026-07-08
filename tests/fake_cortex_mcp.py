"""Fake Cortex MCP server for tests.

Speaks the same newline-delimited JSON-RPC protocol as cortex.mcp.server and
serves canned answers shaped like the real tools' payloads. Launched by tests
via AXON_CORTEX_MCP_CMD. Env knobs:

- FAKE_CORTEX_MISSING_DB=1: tools error with missing_db until cortex_refresh
  is called (exercises the adapter's refresh-and-retry path).
- FAKE_CORTEX_NO_TOOLS=1: advertise no tools (exercises the handshake guard).
"""

from __future__ import annotations

import json
import os
import sys

STATE = {"has_db": os.environ.get("FAKE_CORTEX_MISSING_DB") != "1"}

TOOL_NAMES = [] if os.environ.get("FAKE_CORTEX_NO_TOOLS") == "1" else [
    "cortex_query", "cortex_search_symbols", "cortex_references",
    "cortex_relations", "cortex_refresh",
]


def _content(payload, is_error=False):
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": is_error}


def _call(name, args):
    if name == "cortex_refresh":
        STATE["has_db"] = True
        return _content({
            "summary": {"new_files": 4, "updated_files": 0, "deleted_files": 0, "unchanged_files": 0},
            "stale": False,
        })
    if not STATE["has_db"]:
        return _content(
            {"error": "missing_db", "message": "Cortex database not found."},
            is_error=True,
        )
    if name == "cortex_query":
        return _content({
            "task": args.get("task", ""),
            "items": [
                {"path": "calc/core.py", "kind": "code", "score": 2.0, "content": "def divide(a, b):"},
                {"path": "calc/core.py", "kind": "code", "score": 1.9, "content": "def divide(a, b):"},
                {"path": "calc/api.py", "kind": "code", "score": 1.0, "content": "return divide(a, b)"},
            ],
        })
    if name == "cortex_search_symbols":
        items = []
        if args.get("query") == "divide":
            items = [{
                "node_id": "symbol:calc/core.py:divide", "kind": "function", "label": "divide",
                "source_ref": "calc/core.py", "granularity": "symbol",
                "signature": "def divide(a, b)", "span_start": 4, "span_end": 5,
            }]
        return _content({"items": items})
    if name == "cortex_references":
        return _content({
            "items": {
                "code": ["calc/api.py:4", "calc/core.py:4"],
                "script": [], "doc": ["README.md:2"], "config": [], "other": [],
            },
            "truncated": False,
            "returned_count": 3,
        })
    if name == "cortex_relations":
        # Emulate `calls` edges: use_divide (@ core.py:7) calls divide; the
        # queried symbol here is divide's own node, whose only callee is `abs`.
        items = []
        if args.get("relation") == "calls" and "divide" in str(args.get("symbol", "")):
            items = [
                {"relation": "calls", "source": "divide @ calc/core.py:4", "target": "abs"},
                # A sibling edge that must be filtered out by exact-source match:
                {"relation": "calls", "source": "use_divide @ calc/core.py:7", "target": "divide"},
            ]
        return _content({"items": items, "truncated": False, "returned_count": len(items)})
    return _content({"error": "unknown_tool", "message": name}, is_error=True)


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        frame = json.loads(line)
        method = frame.get("method")
        request_id = frame.get("id")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            result = {
                "protocolVersion": frame.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-cortex", "version": "0"},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": "", "inputSchema": {"type": "object"}} for n in TOOL_NAMES]}
        elif method == "tools/call":
            params = frame.get("params") or {}
            result = _call(params.get("name", ""), params.get("arguments") or {})
        else:
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
