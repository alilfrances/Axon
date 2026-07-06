from __future__ import annotations

from axon import cli, server


def test_server_tools_registered():
    tools = server.app.list_tools()

    if hasattr(tools, "__await__"):
        import asyncio

        tools = asyncio.run(tools)
    names = {tool.name for tool in tools}
    assert {"index", "graph_context", "search", "run_tests"} <= names


def test_server_underlying_functions(fixture_repo):
    repo = fixture_repo()

    stats = server.index_repo(str(repo))
    ctx = server.graph_context(str(repo), "divide")
    hits = server.search(str(repo), "divide", 3)

    assert stats["files"] >= 3
    assert ctx["backend"] in {"builtin", "cortex-fallback-builtin"}
    assert hits


def test_cli_doctor_no_crash(capsys):
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out

    assert "python:" in out
    assert "active_backend:" in out
