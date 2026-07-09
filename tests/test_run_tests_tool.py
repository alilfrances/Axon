from __future__ import annotations

import sys
from pathlib import Path

from axon.tools import run_tests as run_tests_module


def test_find_ctest_build_dir_fallback_prefers_shallow_non_deps_dir(tmp_path: Path):
    repo = tmp_path / "repo"
    shallow = repo / "custom-build"
    deps = repo / "z_deeper" / "_deps" / "googletest-build"
    shallow.mkdir(parents=True)
    deps.mkdir(parents=True)
    (shallow / "CTestTestfile.cmake").write_text("# top-level generated tests\n", encoding="utf-8")
    (deps / "CTestTestfile.cmake").write_text("# dependency tests\n", encoding="utf-8")

    assert run_tests_module._find_ctest_build_dir(repo) == shallow


def test_run_test_suite_parses_pytest_failure(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(run_tests_module, "ensure_venv", lambda repo, path: Path(sys.executable))

    result = run_tests_module.run_test_suite(repo, timeout_s=30)

    assert result["passed"] >= 1
    assert result["failed"] >= 1
    assert any("test_divide_zero_returns_none" in f["test_id"] for f in result["failures"])
