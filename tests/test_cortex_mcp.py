from __future__ import annotations

import sys
from pathlib import Path

import pytest

from axon.providers.cortex import CortexProvider

_FAKE_SERVER = Path(__file__).parent / "fake_cortex_mcp.py"


@pytest.fixture
def mcp_env(monkeypatch):
    # Disable the CLI rung so assertions exercise MCP vs builtin deterministically,
    # even on machines where a real cortex binary is installed.
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: False))
    monkeypatch.setenv("AXON_CORTEX_MCP_CMD", f"{sys.executable} {_FAKE_SERVER}")


@pytest.fixture
def provider(mcp_env, fixture_repo):
    provider = CortexProvider(fixture_repo())
    yield provider
    provider.close()


def test_mcp_search_maps_and_dedupes(provider):
    hits = provider.search("divide", 5)

    assert hits, "expected hits from the MCP transport"
    assert all(hit.backend == "cortex-mcp" for hit in hits)
    assert hits[0].file == "calc/core.py"
    keys = [(hit.file, hit.snippet) for hit in hits]
    assert len(keys) == len(set(keys)), "duplicate rows should be collapsed"


def test_mcp_graph_context_maps_symbols_and_references(provider):
    ctx = provider.graph_context("divide")

    assert ctx.backend == "cortex-mcp"
    assert ctx.degraded is False
    assert ctx.definitions[0]["file"] == "calc/core.py"
    assert ctx.definitions[0]["line"] == 4
    assert any(c["file"] == "calc/api.py" for c in ctx.callers)
    # The definition site itself must not be listed as a caller.
    assert not any(c["file"] == "calc/core.py" and c["line"] == 4 for c in ctx.callers)
    assert {"calc/api.py", "calc/core.py", "README.md"} <= set(ctx.blast_radius)
    # callees come from `calls` edges; a sibling function's edge whose source
    # is not this symbol must be filtered out.
    assert ctx.callees == ["abs"]


def test_mcp_graph_context_unknown_symbol_falls_back_with_note(provider):
    ctx = provider.graph_context("no_such_symbol_anywhere")

    assert ctx.backend == "cortex-fallback-builtin"
    assert "Python-only" in ctx.note


def test_mcp_index_uses_persistent_refresh(provider):
    stats = provider.index(provider.repo)

    assert stats["backend"] == "cortex-mcp"
    assert stats["indexed"] is True
    assert stats["summary"]["new_files"] == 4


def test_mcp_missing_db_triggers_refresh_and_retry(mcp_env, monkeypatch, fixture_repo):
    monkeypatch.setenv("FAKE_CORTEX_MISSING_DB", "1")
    provider = CortexProvider(fixture_repo())
    try:
        hits = provider.search("divide", 3)
        assert hits and hits[0].backend == "cortex-mcp"
    finally:
        provider.close()


def test_mcp_launch_failure_falls_back_to_builtin(monkeypatch, fixture_repo):
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: False))
    monkeypatch.setenv("AXON_CORTEX_MCP_CMD", "/nonexistent/cortex-mcp-binary mcp")
    provider = CortexProvider(fixture_repo())
    try:
        hits = provider.search("divide", 3)
        assert provider._mcp_state == "failed"
        assert hits and all(hit.backend == "cortex-fallback-builtin" for hit in hits)
    finally:
        provider.close()


def test_mcp_server_without_required_tools_falls_back(mcp_env, monkeypatch, fixture_repo):
    monkeypatch.setenv("FAKE_CORTEX_NO_TOOLS", "1")
    provider = CortexProvider(fixture_repo())
    try:
        hits = provider.search("divide", 3)
        assert provider._mcp_state == "failed"
        assert hits and all(hit.backend == "cortex-fallback-builtin" for hit in hits)
    finally:
        provider.close()
