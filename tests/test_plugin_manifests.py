from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_codex_plugin_manifest_exposes_axon_mcp_server():
    manifest = _load(".codex-plugin/plugin.json")
    claude_manifest = _load(".claude-plugin/plugin.json")
    mcp = _load(".mcp.json")

    assert manifest["name"] == "axon"
    assert manifest["version"] == claude_manifest["version"]
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["interface"]["category"] == "Developer Tools"
    assert "axon" in mcp
    assert "CLAUDE_PLUGIN_ROOT" not in json.dumps(mcp)
    assert mcp["axon"] == {
        "command": "python3",
        "args": ["./bin/axon-mcp.py"],
        "cwd": ".",
    }
    assert claude_manifest["mcpServers"]["axon"]["command"] == "python3"
    assert claude_manifest["mcpServers"]["axon"]["args"] == [
        "${CLAUDE_PLUGIN_ROOT}/bin/axon-mcp.py"
    ]


def test_versions_stay_locked():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    codex_manifest = _load(".codex-plugin/plugin.json")
    claude_manifest = _load(".claude-plugin/plugin.json")
    marketplace = _load(".claude-plugin/marketplace.json")

    from axon import __version__

    version = pyproject["project"]["version"]
    assert __version__ == version
    assert codex_manifest["version"] == version
    assert claude_manifest["version"] == version
    assert marketplace["metadata"]["version"] == version
    assert marketplace["plugins"][0]["version"] == version


def test_plugin_launcher_uses_dependency_free_stdio_adapter():
    script = (ROOT / "bin/axon-mcp.py").read_text(encoding="utf-8")

    assert 'pip install' not in script
    assert 'AXON_PLUGIN_VENV' not in script
    assert 'sys.path.insert(0, str(SRC))' in script
    assert 'from axon.mcp_stdio import main' in script
    assert '--system-site-packages' not in script
    assert 'VENV="$ROOT/.venv-plugin"' not in script


def test_codex_mcp_config_launches_from_plugin_root(tmp_path):
    mcp = _load(".mcp.json")["axon"]
    env = os.environ.copy()
    env["AXON_CORTEX_MCP_CMD"] = "off"
    env["AXON_DATA_DIR"] = str(tmp_path / "axon_data")
    proc = subprocess.run(
        [mcp["command"], *mcp["args"]],
        input=(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}\n'
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        ),
        cwd=ROOT / mcp["cwd"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    responses = [json.loads(line) for line in proc.stdout.splitlines()]

    assert responses[0]["result"]["serverInfo"]["name"] == "axon"
    assert responses[0]["result"]["serverInfo"]["version"] == _load(".codex-plugin/plugin.json")["version"]
    names = {tool["name"] for tool in responses[1]["result"]["tools"]}
    assert {"index", "graph_context", "search", "status", "localize"} <= names


def test_duplicate_codex_launcher_files_are_removed():
    assert not (ROOT / ".agents/plugins/marketplace.json").exists()
    assert not (ROOT / ".claude-plugin/serve.sh").exists()
