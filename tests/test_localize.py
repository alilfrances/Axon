from __future__ import annotations

from pathlib import Path
import subprocess

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


class StringCallerProvider(BuiltinProvider):
    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        return []

    def graph_context(self, symbol: str) -> GraphContext:
        return GraphContext(symbol=symbol, callers=["pkg/caller.py"], backend=self.backend)


class Bm25OnlyProvider(BuiltinProvider):
    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        return [SearchHit(file="pkg/only.py", line=3, score=1.0, snippet="", backend=self.backend)]

    def graph_context(self, symbol: str) -> GraphContext:
        return GraphContext(symbol=symbol, backend=self.backend)


class LowScoreBm25OnlyProvider(BuiltinProvider):
    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        return [SearchHit(file="pkg/only.py", line=3, score=0.016, snippet="", backend=self.backend)]

    def graph_context(self, symbol: str) -> GraphContext:
        return GraphContext(symbol=symbol, backend=self.backend)


class MixedScoreProvider(BuiltinProvider):
    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        return [
            SearchHit(file="pkg/junk.py", line=1, score=0.016, snippet="", backend=self.backend),
            SearchHit(file="pkg/target.py", line=4, score=8.0, snippet="", backend=self.backend),
        ][:k]

    def graph_context(self, symbol: str) -> GraphContext:
        return GraphContext(symbol=symbol, backend=self.backend)


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


def test_localize_tolerates_string_graph_callers(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "caller.py").write_text("def invoke():\n    return BrokenCaller()\n", encoding="utf-8")
    provider = StringCallerProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize(provider, index, "BrokenCaller fails", k=3)

        assert result["suspects"]
        assert any(suspect["file"] == "pkg/caller.py" for suspect in result["suspects"])
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
    assert result[0]["confidence"] == "medium"
    assert result[1]["confidence"] == "low"


def test_fuse_marks_three_source_suspect_high_confidence():
    result = _fuse(
        [
            ("traceback", [{"file": "target.py", "line": 2, "evidence": "traceback frame #1 in run"}]),
            ("bm25", [{"file": "target.py", "line": 3, "evidence": "bm25 rank 1"}]),
            ("graph", [{"file": "target.py", "line": 4, "evidence": "calls Widget (graph)"}]),
        ],
        k=1,
    )

    assert result[0]["confidence"] == "high"


def test_fuse_demotes_near_zero_bm25_rank_one_below_stronger_signals():
    result = _fuse(
        [
            (
                "bm25",
                [
                    {"file": "junk.py", "line": 1, "evidence": "bm25 rank 1", "raw_score": 0.016},
                    {"file": "target.py", "line": 7, "evidence": "bm25 rank 2", "raw_score": 8.0},
                ],
            ),
            ("graph", [{"file": "graph.py", "line": 3, "evidence": "calls Widget (graph)"}]),
        ],
        k=3,
    )

    assert [item["file"] for item in result] == ["target.py", "graph.py", "junk.py"]
    assert result[0]["confidence"] == "medium"
    assert result[2]["confidence"] == "low"


def test_localize_promotes_lone_strong_bm25_top_suspect_to_medium_confidence(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "only.py").write_text("def handle():\n    return 1\n", encoding="utf-8")
    provider = Bm25OnlyProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize(provider, index, "WidgetFailure happens", k=3)

        assert result["suspects"][0]["file"] == "pkg/only.py"
        assert result["suspects"][0]["confidence"] == "medium"
        assert result["low_confidence"] is False
    finally:
        provider.close()
        index.close()


def test_localize_flags_lone_near_zero_bm25_top_suspect_low_confidence(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "only.py").write_text("def handle():\n    return 1\n", encoding="utf-8")
    provider = LowScoreBm25OnlyProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize(provider, index, "WidgetFailure happens", k=3)

        assert result["suspects"][0]["file"] == "pkg/only.py"
        assert result["suspects"][0]["confidence"] == "low"
        assert result["low_confidence"] is True
        assert "top suspect low-confidence" in result["note"]
    finally:
        provider.close()
        index.close()


def test_localize_strong_bm25_hit_surfaces_above_rank_one_junk(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "junk.py").write_text("def unrelated():\n    return 1\n", encoding="utf-8")
    (repo / "pkg" / "target.py").write_text("def handle():\n    return 2\n", encoding="utf-8")
    provider = MixedScoreProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize(provider, index, "broken behavior", k=3)

        assert result["suspects"][0]["file"] == "pkg/target.py"
        assert result["suspects"][0]["confidence"] == "medium"
        assert any(suspect["file"] == "pkg/junk.py" for suspect in result["suspects"][1:])
    finally:
        provider.close()
        index.close()


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


def test_localize_recency_boosts_recently_changed_file(git_fixture_repo):
    from axon.tools.localize import _recency_candidates

    root = git_fixture_repo()
    (root / "calc" / "api.py").write_text(
        "from calc.core import divide\n\n"
        "def ratio(a, b):\n"
        "    return divide(a, b)\n\n"
        "def extra():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "touch api"], cwd=root, check=True, capture_output=True, text=True)

    cands = _recency_candidates(str(root))
    assert cands and cands[0]["file"] == "calc/api.py"
    assert "recent" in cands[0]["evidence"]

    provider = BuiltinProvider(root)
    provider.index(root)
    index = RepoIndex(root)
    try:
        index.refresh()
        result = localize(provider, index, "ratio computes wrong value in api")
        files = [s["file"] for s in result["suspects"]]
        assert "calc/api.py" in files
    finally:
        provider.close()
        index.close()


def test_recency_candidates_non_git_repo_empty(fixture_repo):
    from axon.tools.localize import _recency_candidates

    assert _recency_candidates(str(fixture_repo())) == []


def test_localize_attaches_enclosing_functions(fixture_repo):
    root = fixture_repo()
    provider = BuiltinProvider(root)
    provider.index(root)
    index = RepoIndex(root)
    try:
        index.refresh()
        bug = (
            "divide crashes\n"
            'Traceback (most recent call last):\n'
            '  File "calc/core.py", line 5, in divide\n'
            "ZeroDivisionError: division by zero\n"
        )
        result = localize(provider, index, bug)
        top = result["suspects"][0]
        assert top["file"] == "calc/core.py"
        quals = [f["qualname"] for f in top.get("functions", [])]
        assert "divide" in quals
    finally:
        provider.close()
        index.close()
