from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _frame(method: str, params: dict | None = None, request_id: int | None = 1) -> str:
    frame = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        frame["id"] = request_id
    if params is not None:
        frame["params"] = params
    return json.dumps(frame)


def _run_mcp(frames: list[str], tmp_path: Path) -> list[dict]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["AXON_CORTEX_MCP_CMD"] = "off"
    env["AXON_DATA_DIR"] = str(tmp_path / "axon_data")
    proc = subprocess.run(
        [sys.executable, "-S", "-m", "axon.mcp_stdio"],
        input="\n".join(frames) + "\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return [json.loads(line) for line in proc.stdout.splitlines()]


def test_mcp_stdio_initialize_and_tools_list_under_python_s(tmp_path):
    responses = _run_mcp(
        [
            _frame("initialize", {"protocolVersion": "2024-11-05"}, 1),
            _frame("notifications/initialized", request_id=None),
            _frame("tools/list", request_id=2),
        ],
        tmp_path,
    )

    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "axon"
    assert responses[0]["result"]["capabilities"]["tools"]["listChanged"] is False
    tools = responses[1]["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"index", "graph_context", "search", "status", "localize"} <= names
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)


def test_mcp_stdio_tools_call_status(tmp_path, fixture_repo):
    repo = fixture_repo()
    responses = _run_mcp(
        [
            _frame("initialize", request_id=1),
            _frame("tools/call", {"name": "status", "arguments": {"repo": str(repo)}}, 2),
        ],
        tmp_path,
    )

    result = responses[1]["result"]
    payload = json.loads(result["content"][0]["text"])
    assert payload["backend"] in {"cortex", "builtin", "grep", "cortex-fallback-builtin"}
    assert payload["python_files"] >= 3


def test_mcp_stdio_reports_protocol_and_tool_errors(tmp_path):
    responses = _run_mcp(
        [
            "{not json",
            _frame("nope", request_id=1),
            _frame("tools/call", {"name": "missing", "arguments": {}}, 2),
        ],
        tmp_path,
    )

    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["error"]["code"] == -32601
    tool_result = responses[2]["result"]
    assert tool_result["isError"] is True
    assert json.loads(tool_result["content"][0]["text"])["error"] == "unknown_tool"
