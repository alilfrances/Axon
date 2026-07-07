from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from axon.tools import verify_fix


REPRO = "tests/test_calc.py::test_divide_zero_returns_none"


def _status(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def _patch(new_core: str) -> str:
    return (
        "--- a/calc/core.py\n"
        "+++ b/calc/core.py\n"
        "@@ -1,8 +1,10 @@\n"
        " def add(a, b):\n"
        f"{new_core}"
        " \n"
        " def safe_divide(a, b):\n"
        "     return divide(a, b)\n"
    )


def _fix_patch() -> str:
    return _patch(
        "     return a + b\n"
        " \n"
        " def divide(a, b):\n"
        "-    return a / b\n"
        "+    if b == 0:\n"
        "+        return None\n"
        "+    return a / b\n"
    )


def test_verify_fix_passes_and_reverts(monkeypatch, git_fixture_repo):
    repo = git_fixture_repo()
    monkeypatch.setattr(verify_fix, "ensure_venv", lambda repo, path: Path(sys.executable))

    result = verify_fix.verify_fix(str(repo), _fix_patch(), REPRO, timeout=30)

    assert result["verdict"] == "pass"
    assert result["applied"] is True
    assert result["reverted"] is True
    assert _status(repo) == ""


def test_verify_fix_does_not_fix_and_reverts(monkeypatch, git_fixture_repo):
    repo = git_fixture_repo()
    monkeypatch.setattr(verify_fix, "ensure_venv", lambda repo, path: Path(sys.executable))
    patch = (
        "--- a/calc/core.py\n"
        "+++ b/calc/core.py\n"
        "@@ -2,7 +2,7 @@ def add(a, b):\n"
        "     return a + b\n"
        " \n"
        " def divide(a, b):\n"
        "-    return a / b\n"
        "+    return a / b  # still broken\n"
        " \n"
        " def safe_divide(a, b):\n"
        "     return divide(a, b)\n"
    )

    result = verify_fix.verify_fix(str(repo), patch, REPRO, timeout=30)

    assert result["verdict"] == "fix-does-not-fix"
    assert result["applied"] is True
    assert result["reverted"] is True
    assert _status(repo) == ""


def test_verify_fix_reports_regressions_and_reverts(monkeypatch, git_fixture_repo):
    repo = git_fixture_repo()
    monkeypatch.setattr(verify_fix, "ensure_venv", lambda repo, path: Path(sys.executable))
    patch = _patch(
        "-    return a + b\n"
        "+    return a - b\n"
        " \n"
        " def divide(a, b):\n"
        "-    return a / b\n"
        "+    if b == 0:\n"
        "+        return None\n"
        "+    return a / b\n"
    )

    result = verify_fix.verify_fix(str(repo), patch, REPRO, timeout=30)

    assert result["verdict"] == "regressions"
    assert any("test_add" in test_id for test_id in result["regressions"])
    assert result["reverted"] is True
    assert _status(repo) == ""
