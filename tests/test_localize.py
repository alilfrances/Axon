from __future__ import annotations

from axon.index import RepoIndex
from axon.providers.builtin import BuiltinProvider
from axon import server
from axon.tools.localize import localize


def test_localize_traceback_ranks_frame_file_first(fixture_repo):
    repo = fixture_repo()
    provider = BuiltinProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        bug_text = '''ZeroDivisionError: division by zero
Traceback (most recent call last):
  File "calc/api.py", line 4, in ratio
    return divide(a, b)
  File "calc/core.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero
'''

        result = localize(provider, index, bug_text, k=3)

        assert result["suspects"][0]["file"] == "calc/core.py"
        assert any("traceback frame" in item for item in result["suspects"][0]["evidence"])
    finally:
        provider.close()
        index.close()


def test_localize_no_traceback_finds_core_file_top_three(fixture_repo):
    repo = fixture_repo()
    provider = BuiltinProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize(
            provider,
            index,
            "safe_divide returns ZeroDivisionError instead of handling divide by zero",
            k=3,
        )

        files = [suspect["file"] for suspect in result["suspects"]]
        assert "calc/core.py" in files[:3]
    finally:
        provider.close()
        index.close()


def test_server_registers_and_runs_localize(fixture_repo):
    tools = server.app.list_tools()
    if hasattr(tools, "__await__"):
        import asyncio

        tools = asyncio.run(tools)
    assert "localize" in {tool.name for tool in tools}

    repo = fixture_repo()
    result = server.localize(str(repo), "divide by zero in ratio", k=3)

    assert result["suspects"]
