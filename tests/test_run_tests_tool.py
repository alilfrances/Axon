from __future__ import annotations

import sys
from pathlib import Path

from axon.tools import run_tests as run_tests_module


def test_run_test_suite_parses_pytest_failure(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(run_tests_module, "ensure_venv", lambda repo, path: Path(sys.executable))

    result = run_tests_module.run_test_suite(repo, timeout_s=30)

    assert result["passed"] >= 1
    assert result["failed"] >= 1
    assert any("test_divide_zero_returns_none" in f["test_id"] for f in result["failures"])
