from __future__ import annotations

import sys
from pathlib import Path

from axon.tools import repro


def test_repro_scaffold_writes_skeleton_red(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(repro, "ensure_venv", lambda repo, path: Path(sys.executable))

    result = repro.repro_scaffold(str(repo), "Divide By Zero!")

    assert result["created"] is True
    assert result["currently_fails"] is True
    assert Path(result["path"]).exists()
    assert result["test_result"]["failed"] >= 1


def test_repro_scaffold_rejects_bad_body_without_file(fixture_repo):
    repo = fixture_repo()

    result = repro.repro_scaffold(str(repo), "bad", "assert True\n")

    assert result["created"] is False
    assert "def test_" in result["error"]
    assert not (repo / "tests" / "repros" / "test_bad.py").exists()
