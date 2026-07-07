from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_codex_plugin_manifest_exposes_axon_mcp_server():
    manifest = _load(".codex-plugin/plugin.json")
    mcp = _load(".mcp.json")

    assert manifest["name"] == "axon"
    assert manifest["version"] == _load(".claude-plugin/plugin.json")["version"]
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["interface"]["category"] == "Developer Tools"
    assert "axon" in mcp["mcpServers"]
    assert mcp["mcpServers"]["axon"]["command"] == "sh"
    assert mcp["mcpServers"]["axon"]["args"][0].endswith(".claude-plugin/serve.sh")


def test_plugin_launcher_uses_writable_cache_venv():
    script = (ROOT / ".claude-plugin/serve.sh").read_text(encoding="utf-8")

    assert 'AXON_PLUGIN_VENV' in script
    assert 'CACHE_ROOT="${XDG_CACHE_HOME:-${TMPDIR:-/tmp}}"' in script
    assert 'VENV="$ROOT/.venv-plugin"' not in script


def test_codex_marketplace_points_at_repo_root():
    marketplace = _load(".agents/plugins/marketplace.json")
    [entry] = marketplace["plugins"]

    assert marketplace["name"] == "axon"
    assert entry["name"] == "axon"
    assert entry["source"] == {"source": "local", "path": "./"}
    assert entry["policy"]["installation"] == "AVAILABLE"
