from __future__ import annotations

from pathlib import Path

from axon.tools import repro


def test_repro_scaffold_writes_skeleton_red(fixture_repo):
    repo = fixture_repo()

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


def test_repro_classifies_exception(fixture_repo):
    root = fixture_repo()
    body = (
        "from calc.core import divide\n\n"
        "def test_zero_division_repro():\n"
        "    divide(1, 0)\n"
    )
    result = repro.repro_scaffold(str(root), "zero division", body)
    assert result["currently_fails"]
    assert result["failure_kind"] == "exception:ZeroDivisionError"
    assert "ZeroDivisionError" in result["failure_excerpt"]


def test_repro_classifies_passes(fixture_repo):
    root = fixture_repo()
    body = "def test_trivial():\n    assert True\n"
    result = repro.repro_scaffold(str(root), "trivial", body)
    assert result["failure_kind"] == "passes"
