"""FastMCP adapter for Axon tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from axon import tool_registry as _tool_registry

TOOL_SPECS = _tool_registry.TOOL_SPECS
graph_context = _tool_registry.graph_context
index_repo = _tool_registry.index_repo
inspect = _tool_registry.inspect
investigate = _tool_registry.investigate
localize = _tool_registry.localize
rank_patches = _tool_registry.rank_patches
refute = _tool_registry.refute
repro = _tool_registry.repro
run_tests = _tool_registry.run_tests
sast_scan = _tool_registry.sast_scan
search = _tool_registry.search
spectrum = _tool_registry.spectrum
status = _tool_registry.status
triage = _tool_registry.triage
verify_fix = _tool_registry.verify_fix

app = FastMCP("axon")

for spec in TOOL_SPECS:
    app.tool(name=spec.name)(spec.func)


def main() -> None:
    app.run("stdio")


server = app
