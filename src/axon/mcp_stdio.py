"""Dependency-free MCP stdio adapter for Axon tools."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, TextIO

from axon import __version__
from axon.tool_registry import TOOL_BY_NAME, TOOL_SPECS

_DEFAULT_PROTOCOL_VERSION = "2024-11-05"


def main() -> int:
    serve(sys.stdin, sys.stdout)
    return 0


def serve(stdin: TextIO, stdout: TextIO) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            _write(stdout, _error(None, -32700, "Parse error"))
            continue
        if not isinstance(frame, dict):
            _write(stdout, _error(None, -32600, "Invalid Request"))
            continue

        request_id = frame.get("id")
        method = frame.get("method")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "notifications/initialized":
            continue
        if method == "initialize":
            _write(stdout, _result(request_id, _initialize_result(params)))
        elif method == "tools/list":
            _write(stdout, _result(request_id, {"tools": [_tool_payload(spec) for spec in TOOL_SPECS]}))
        elif method == "tools/call":
            _write(stdout, _result(request_id, _call_tool(params)))
        elif request_id is not None:
            _write(stdout, _error(request_id, -32601, "Method not found"))


def _initialize_result(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": params.get("protocolVersion") or _DEFAULT_PROTOCOL_VERSION,
        "capabilities": {
            "experimental": {},
            "prompts": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "tools": {"listChanged": False},
        },
        "serverInfo": {"name": "axon", "version": _version()},
    }


def _call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}

    spec = TOOL_BY_NAME.get(name)
    if spec is None:
        return _tool_result({"error": "unknown_tool", "message": str(name)}, is_error=True)

    try:
        return _tool_result(spec.call(arguments))
    except Exception as exc:
        return _tool_result(
            {
                "error": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=8),
            },
            is_error=True,
        )


def _tool_payload(spec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": spec.input_schema,
    }


def _tool_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    if is_error:
        result["isError"] = True
    return result


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write(stdout: TextIO, frame: dict[str, Any]) -> None:
    stdout.write(json.dumps(frame) + "\n")
    stdout.flush()


def _version() -> str:
    return __version__


if __name__ == "__main__":
    raise SystemExit(main())
