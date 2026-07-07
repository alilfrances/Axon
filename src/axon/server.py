"""Axon MCP server."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from axon.providers.base import ContextProvider
from axon.providers.select import select_provider
from axon.index import RepoIndex
from axon.tools.localize import localize as localize_tool
from axon.tools.run_tests import run_test_suite

app = FastMCP("axon")
_providers: dict[str, ContextProvider] = {}


def _provider(repo: str) -> ContextProvider:
    root = str(Path(repo).resolve())
    if root not in _providers:
        _providers[root] = select_provider(Path(root))
    return _providers[root]


@app.tool(name="index")
def index_repo(repo: str) -> dict:
    return _provider(repo).index(Path(repo))


@app.tool(name="graph_context")
def graph_context(repo: str, symbol: str) -> dict:
    return asdict(_provider(repo).graph_context(symbol))


@app.tool(name="search")
def search(repo: str, query: str, k: int = 10) -> list[dict]:
    return [asdict(hit) for hit in _provider(repo).search(query, k)]


@app.tool(name="run_tests")
def run_tests(repo: str, test_target: str | None = None, timeout_s: int = 120) -> dict:
    return run_test_suite(Path(repo), test_target, timeout_s)


@app.tool(name="localize")
def localize(repo: str, bug_text: str, k: int = 10, failing_test: str | None = None) -> dict:
    provider = _provider(repo)
    index = _repo_index(provider, Path(repo))
    return localize_tool(provider, index, bug_text, k, failing_test)


def _repo_index(provider: ContextProvider, repo: Path) -> RepoIndex:
    indexer = getattr(provider, "indexer", None)
    if isinstance(indexer, RepoIndex):
        return indexer
    fallback = getattr(provider, "_fallback", None)
    indexer = getattr(fallback, "indexer", None)
    if isinstance(indexer, RepoIndex):
        return indexer
    indexer = RepoIndex(repo)
    indexer.refresh()
    return indexer


def main() -> None:
    app.run("stdio")


server = app
