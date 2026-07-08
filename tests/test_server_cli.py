from __future__ import annotations

from axon import cli, server


def test_server_tools_registered():
    tools = server.app.list_tools()

    if hasattr(tools, "__await__"):
        import asyncio

        tools = asyncio.run(tools)
    names = {tool.name for tool in tools}
    assert {"index", "graph_context", "search", "status", "run_tests"} <= names


def test_server_underlying_functions(fixture_repo):
    repo = fixture_repo()

    stats = server.index_repo(str(repo))
    ctx = server.graph_context(str(repo), "divide")
    hits = server.search(str(repo), "divide", 3)
    status = server.status(str(repo))

    assert stats["files"] >= 3
    assert ctx["backend"] in {"builtin", "cortex-fallback-builtin"}
    assert hits
    assert status["backend"] in {"builtin", "cortex-fallback-builtin"}
    assert status["python_files"] >= 3
    assert status["text_files"] >= status["python_files"]


def test_cli_doctor_no_crash(capsys):
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out

    assert "python:" in out
    assert "active_backend:" in out


def test_cli_index_uses_provider_ladder(monkeypatch, tmp_path, capsys):
    calls = []

    class StubProvider:
        def index(self, path):
            return {"backend": "stub", "path": str(path)}

    def fake_select_provider(path, prefer=None):
        calls.append((path, prefer))
        return StubProvider()

    monkeypatch.setattr(cli, "select_provider", fake_select_provider)

    assert cli.main(["index", str(tmp_path)]) == 0

    assert calls == [(tmp_path, None)]
    assert "'backend': 'stub'" in capsys.readouterr().out
