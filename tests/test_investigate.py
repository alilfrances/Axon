from __future__ import annotations

from axon.index import RepoIndex
from axon.providers.builtin import BuiltinProvider


def _setup(root):
    provider = BuiltinProvider(root)
    provider.index(root)
    index = RepoIndex(root)
    index.refresh()
    return provider, index


BUG = (
    "divide crashes on zero\n"
    "Traceback (most recent call last):\n"
    '  File "calc/core.py", line 5, in divide\n'
    "ZeroDivisionError: division by zero\n"
)


def test_investigate_bundles_evidence(fixture_repo):
    from axon.tools.investigate import investigate

    root = fixture_repo()
    provider, index = _setup(root)
    try:
        result = investigate(
            provider,
            index,
            str(root),
            BUG,
            failing_test="tests/test_calc.py::test_divide_zero_returns_none",
        )
        assert result["suspects"][0]["file"] == "calc/core.py"
        assert result["runtime"] and result["runtime"]["failures"]
        snippet_quals = [s["qualname"] for s in result["snippets"]]
        assert "divide" in snippet_quals
        snippet = next(s for s in result["snippets"] if s["qualname"] == "divide")
        assert "return a / b" in snippet["code"]
        assert any("repro" in step for step in result["workflow"])
    finally:
        provider.close()
        index.close()


def test_investigate_without_failing_test(fixture_repo):
    from axon.tools.investigate import investigate

    root = fixture_repo()
    provider, index = _setup(root)
    try:
        result = investigate(provider, index, str(root), BUG)
        assert result["runtime"] is None
        assert result["suspects"]
    finally:
        provider.close()
        index.close()


def test_investigate_respects_budget(fixture_repo):
    import json

    from axon.tools.investigate import investigate

    root = fixture_repo()
    provider, index = _setup(root)
    try:
        result = investigate(provider, index, str(root), BUG, budget_chars=1200)
        assert result["truncated"] is True
        assert len(json.dumps(result)) <= 2400
    finally:
        provider.close()
        index.close()
