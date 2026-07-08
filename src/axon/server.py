"""FastMCP adapter for Axon tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from axon.tool_registry import (
    TOOL_SPECS,
    graph_context,
    index_repo,
    inspect,
    investigate,
    localize,
    rank_patches,
    refute,
    repro,
    run_tests,
    sast_scan,
    search,
    spectrum,
    status,
    triage,
    verify_fix,
)

app = FastMCP("axon")

for spec in TOOL_SPECS:
    app.tool(name=spec.name)(spec.func)


def main() -> None:
    app.run("stdio")


server = app
