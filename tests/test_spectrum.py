from __future__ import annotations

import sys
from pathlib import Path

from axon.index import RepoIndex
from axon.providers.builtin import BuiltinProvider
from axon.tools import localize as localize_module
from axon.tools import spectrum


def test_spectrum_localize_failing_line(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(spectrum, "ensure_venv", lambda repo, path: Path(sys.executable))

    result = spectrum.spectrum_localize(
        str(repo),
        ["tests/test_calc.py::test_divide_zero_returns_none"],
        ["tests/test_calc.py::test_add"],
        top=10,
    )

    assert result["suspects"]
    assert any(item["file"] == "calc/core.py" for item in result["suspects"])


def test_spectrum_missing_test_degrades(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(spectrum, "ensure_venv", lambda repo, path: Path(sys.executable))

    result = spectrum.spectrum_localize(str(repo), ["tests/test_calc.py::test_missing"], top=5)

    assert result["suspects"] == []
    assert result["degraded"] is True


def test_localize_uses_spectrum_booster(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(spectrum, "ensure_venv", lambda repo, path: Path(sys.executable))
    provider = BuiltinProvider(repo)
    index = RepoIndex(repo)
    try:
        index.refresh()
        result = localize_module.localize(
            provider,
            index,
            "division by zero",
            k=5,
            failing_test="tests/test_calc.py::test_divide_zero_returns_none",
        )
    finally:
        provider.close()
        index.close()

    assert any(
        item["file"] == "calc/core.py"
        and any("spectrum ochiai" in evidence for evidence in item["evidence"])
        for item in result["suspects"]
    )


def test_trace_runner_reports_exit_code(fixture_repo):
    from axon.tools.spectrum import _trace_test

    root = fixture_repo()
    hits, code = _trace_test(root, "tests/test_calc.py::test_add")
    assert code == 0
    assert hits


def test_spectrum_auto_passing_and_functions(fixture_repo):
    from axon.tools.spectrum import spectrum_localize

    root = fixture_repo()
    result = spectrum_localize(str(root), ["tests/test_calc.py::test_divide_zero_returns_none"])
    assert not result["degraded"]
    assert "tests/test_calc.py::test_add" in result["passing_used"]
    quals = [f["qualname"] for f in result["functions"]]
    assert "divide" in quals
    assert "add" not in quals[:1]
