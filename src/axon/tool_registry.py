"""Shared Axon MCP tool registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from axon.index import RepoIndex
from axon.parsing import TEXT_EXTENSIONS, iter_source_files
from axon.providers.base import ContextProvider
from axon.providers.select import select_provider
from axon.tools.inspect_run import inspect_test
from axon.tools.investigate import investigate as investigate_tool
from axon.tools.localize import localize as localize_tool
from axon.tools.rank_patches import rank_patches as rank_patches_tool
from axon.tools.repro import repro_scaffold
from axon.tools.run_tests import run_test_suite
from axon.tools.refute import refute as refute_tool
from axon.tools.sast import sast_scan as sast_scan_tool
from axon.tools.spectrum import spectrum_localize
from axon.tools.triage import triage as triage_tool
from axon.tools.verify_fix import verify_fix as verify_fix_tool

_providers: dict[str, ContextProvider] = {}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    func: Callable[..., Any]
    description: str
    input_schema: dict[str, Any]

    def call(self, arguments: dict[str, Any]) -> Any:
        return self.func(**arguments)


def _provider(repo: str) -> ContextProvider:
    root = str(Path(repo).resolve())
    if root not in _providers:
        _providers[root] = select_provider(Path(root))
    return _providers[root]


def index_repo(repo: str) -> dict:
    return _provider(repo).index(Path(repo))


def graph_context(repo: str, symbol: str) -> dict:
    provider = _provider(repo)
    result = asdict(provider.graph_context(symbol))
    return _with_provider_status(result, provider)


def search(repo: str, query: str, k: int = 10) -> list[dict]:
    return [asdict(hit) for hit in _provider(repo).search(query, k)]


def status(repo: str) -> dict:
    provider = _provider(repo)
    mcp_client = getattr(provider, "_mcp_client", None)
    if callable(mcp_client) and getattr(provider, "_mcp_state", None) == "untried":
        mcp_client()
    root = Path(repo).resolve()
    return {
        "backend": _active_backend(provider),
        "fallback_reason": getattr(provider, "_fallback_reason", None),
        "python_files": len(iter_source_files(root, (".py",))),
        "text_files": len(iter_source_files(root, TEXT_EXTENSIONS)),
    }


def run_tests(repo: str, test_target: str | None = None, timeout_s: int = 120) -> dict:
    return run_test_suite(Path(repo), test_target, timeout_s)


def localize(repo: str, bug_text: str, k: int = 10, failing_test: str | None = None) -> dict:
    provider = _provider(repo)
    index = _repo_index(provider, Path(repo))
    return _with_provider_status(localize_tool(provider, index, bug_text, k, failing_test), provider)


def repro(repo: str, bug_slug: str, test_body: str | None = None) -> dict:
    return repro_scaffold(repo, bug_slug, test_body)


def verify_fix(repo: str, patch: str, repro_test: str, timeout: int = 600, keep: bool = False) -> dict:
    return verify_fix_tool(repo, patch, repro_test, timeout, keep)


def rank_patches(repo: str, patches: list[str], repro_test: str, timeout: int = 600) -> dict:
    return rank_patches_tool(repo, patches, repro_test, timeout)


def spectrum(repo: str, failing_tests: list[str], passing_tests: list[str] | None = None, top: int = 20) -> dict:
    return spectrum_localize(repo, failing_tests, passing_tests, top)


def inspect(repo: str, test_target: str, timeout: int = 120) -> dict:
    return inspect_test(repo, test_target, timeout)


def investigate(repo: str, bug_text: str, failing_test: str | None = None, k: int = 5) -> dict:
    provider = _provider(repo)
    index = _repo_index(provider, Path(repo))
    return _with_provider_status(investigate_tool(provider, index, repo, bug_text, failing_test, k), provider)


def sast_scan(repo: str, timeout: int = 60) -> dict:
    return sast_scan_tool(repo, timeout)


def refute(repo: str, finding: dict, mode: str = "static") -> dict:
    return refute_tool(repo, finding, mode)


def triage(repo: str) -> dict:
    return triage_tool(repo)


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


def _active_backend(provider: ContextProvider) -> str:
    if getattr(provider, "_using_fallback", False):
        return "cortex-fallback-builtin"
    if getattr(provider, "_fallback_reason", None):
        return "cortex-fallback-builtin"
    mcp_state = getattr(provider, "_mcp_state", None)
    if mcp_state == "untried":
        return "cortex-untried"
    if mcp_state == "ready":
        return getattr(provider, "mcp_backend", provider.backend)
    return provider.backend


def _with_provider_status(result: dict, provider: ContextProvider) -> dict:
    result["backend"] = _active_backend(provider)
    result["fallback_reason"] = getattr(provider, "_fallback_reason", None)
    return result


def _schema(properties: dict[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("index", index_repo, "Build or refresh Axon's context index for a repository.", _schema({"repo": _STRING}, ["repo"])),
    ToolSpec(
        "graph_context",
        graph_context,
        "Return definition, caller, callee, and blast-radius context for a symbol.",
        _schema({"repo": _STRING, "symbol": _STRING}, ["repo", "symbol"]),
    ),
    ToolSpec(
        "search",
        search,
        "Search repository snippets relevant to a query.",
        _schema({"repo": _STRING, "query": _STRING, "k": _INTEGER}, ["repo", "query"]),
    ),
    ToolSpec("status", status, "Report Axon's active backend and indexed file counts.", _schema({"repo": _STRING}, ["repo"])),
    ToolSpec(
        "run_tests",
        run_tests,
        "Run a repository test target through Axon's sandbox.",
        _schema({"repo": _STRING, "test_target": _STRING, "timeout_s": _INTEGER}, ["repo"]),
    ),
    ToolSpec(
        "localize",
        localize,
        "Rank likely root-cause files and evidence for a bug report.",
        _schema({"repo": _STRING, "bug_text": _STRING, "k": _INTEGER, "failing_test": _STRING}, ["repo", "bug_text"]),
    ),
    ToolSpec(
        "repro",
        repro,
        "Create or run a lightweight reproduction scaffold for a bug.",
        _schema({"repo": _STRING, "bug_slug": _STRING, "test_body": _STRING}, ["repo", "bug_slug"]),
    ),
    ToolSpec(
        "verify_fix",
        verify_fix,
        "Apply a candidate patch and verify the repro test fails then passes.",
        _schema(
            {"repo": _STRING, "patch": _STRING, "repro_test": _STRING, "timeout": _INTEGER, "keep": _BOOLEAN},
            ["repo", "patch", "repro_test"],
        ),
    ),
    ToolSpec(
        "rank_patches",
        rank_patches,
        "Rank multiple candidate patches by repro and regression results.",
        _schema({"repo": _STRING, "patches": _STRING_ARRAY, "repro_test": _STRING, "timeout": _INTEGER}, ["repo", "patches", "repro_test"]),
    ),
    ToolSpec(
        "spectrum",
        spectrum,
        "Run spectrum-style localization from failing and passing tests.",
        _schema({"repo": _STRING, "failing_tests": _STRING_ARRAY, "passing_tests": _STRING_ARRAY, "top": _INTEGER}, ["repo", "failing_tests"]),
    ),
    ToolSpec(
        "inspect",
        inspect,
        "Capture runtime failure state for one pytest target.",
        _schema({"repo": _STRING, "test_target": _STRING, "timeout": _INTEGER}, ["repo", "test_target"]),
    ),
    ToolSpec(
        "investigate",
        investigate,
        "Collect localization, runtime, and repro evidence for a bug.",
        _schema({"repo": _STRING, "bug_text": _STRING, "failing_test": _STRING, "k": _INTEGER}, ["repo", "bug_text"]),
    ),
    ToolSpec("sast_scan", sast_scan, "Run configured static analysis and return normalized findings.", _schema({"repo": _STRING, "timeout": _INTEGER}, ["repo"])),
    ToolSpec("refute", refute, "Try to disprove or confirm a security finding.", _schema({"repo": _STRING, "finding": {"type": "object"}, "mode": {"type": "string", "description": "Refutation mode; currently only 'static' is supported."}}, ["repo", "finding"])),
    ToolSpec("triage", triage, "Run static scan and adversarial triage for a repository.", _schema({"repo": _STRING}, ["repo"])),
)

TOOL_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}
