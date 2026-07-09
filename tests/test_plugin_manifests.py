from __future__ import annotations

import json
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
    assert "axon" in mcp["mcpServers"]
    assert mcp["mcpServers"]["axon"]["command"] == "python3"
    assert mcp["mcpServers"]["axon"]["args"][0].endswith("bin/axon-mcp.py")
    assert claude_manifest["mcpServers"]["axon"]["command"] == "python3"
    assert claude_manifest["mcpServers"]["axon"]["args"][0].endswith("bin/axon-mcp.py")


def test_plugin_launcher_uses_dependency_free_stdio_adapter():
    script = (ROOT / "bin/axon-mcp.py").read_text(encoding="utf-8")

    assert 'pip install' not in script
    assert 'AXON_PLUGIN_VENV' not in script
    assert 'sys.path.insert(0, str(SRC))' in script
    assert 'from axon.mcp_stdio import main' in script
    assert '--system-site-packages' not in script
    assert 'VENV="$ROOT/.venv-plugin"' not in script


def test_duplicate_codex_launcher_files_are_removed():
    assert not (ROOT / ".agents/plugins/marketplace.json").exists()
    assert not (ROOT / ".claude-plugin/serve.sh").exists()
