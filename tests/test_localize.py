from __future__ import annotations

from pathlib import Path

from axon.index import RepoIndex
from axon.providers.base import GraphContext, SearchHit
from axon.providers.builtin import BuiltinProvider
from axon import server
from axon.tools.localize import _extract_signals, _fuse, _symbol_candidates, localize


class FloodProvider(BuiltinProvider):
    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for idx in range(30):
            hits.append(
                SearchHit(
                    file=f"noise/file_{idx}.py",
                    line=1,
                    score=float(30 - idx),
                    snippet="",
                    backend=self.backend,
                )
            )
        return hits[:k]

    def graph_context(self, symbol: str) -> GraphContext:
        return GraphContext(symbol=symbol, blast_radius=[f"noise/graph_{idx}.py" for idx in range(30)])


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


def test_localize_dotted_path_ranks_matching_file(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg" / "module").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "module" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "module" / "thing.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (repo / "other").mkdir()
    (repo / "other" / "thing.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    provider = BuiltinProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize(provider, index, "Regression in pkg.module.thing during import", k=3)

        assert result["suspects"][0]["file"] == "pkg/module/thing.py"
        assert any("path suffix match" in item for item in result["suspects"][0]["evidence"])
    finally:
        provider.close()
        index.close()


def test_strong_camelcase_identifier_produces_symbol_candidate(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "widgets.py").write_text("class PaymentProcessor:\n    pass\n", encoding="utf-8")
    index = RepoIndex(repo)
    try:
        index.refresh()
        signals = _extract_signals("PaymentProcessor fails when the gateway is disabled")

        assert "PaymentProcessor" in signals["strong_identifiers"]
        assert _symbol_candidates(index, signals["strong_identifiers"])[0]["file"] == "pkg/widgets.py"
    finally:
        index.close()


def test_common_prose_flood_does_not_outrank_traceback(fixture_repo):
    repo = fixture_repo()
    provider = FloodProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        bug_text = '''this should error when using file line value state result data object module package
Traceback (most recent call last):
  File "calc/core.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero
'''

        result = localize(provider, index, bug_text, k=5)

        assert result["suspects"][0]["file"] == "calc/core.py"
    finally:
        provider.close()
        index.close()


def test_fuse_sums_weighted_rrf_across_sources():
    result = _fuse(
        [
            ("bm25", [{"file": "both.py", "line": 2, "evidence": "bm25 rank 1"}]),
            (
                "graph",
                [
                    {"file": "single.py", "line": 3, "evidence": "graph rank 1"},
                    {"file": "both.py", "line": 4, "evidence": "graph rank 2"},
                ],
            ),
        ],
        k=2,
    )

    assert [item["file"] for item in result] == ["both.py", "single.py"]


def test_stopwords_excluded_from_strong_identifiers():
    signals = _extract_signals("This error should happen when using the file line value.")

    assert signals["identifiers"]
    assert not set(signals["strong_identifiers"]) & {
        "This",
        "error",
        "should",
        "when",
        "using",
        "the",
        "file",
        "line",
    }
