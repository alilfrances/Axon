from __future__ import annotations

import sys
from pathlib import Path

from axon import sandbox
from axon.sandbox import ensure_venv, run_in_sandbox


def test_run_in_sandbox_success(tmp_path):
    result = run_in_sandbox([sys.executable, "-c", "print('ok')"], tmp_path)

    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.timed_out is False


def test_run_in_sandbox_timeout(tmp_path):
    result = run_in_sandbox([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, timeout_s=1)

    assert result.timed_out is True
    assert result.duration_s < 3


def test_ensure_venv_installs_pytest_when_missing(tmp_path, monkeypatch):
    """When the venv lacks pytest, ensure_venv attempts an install before
    handing back an interpreter (P3: bundled venv lacks pytest)."""
    calls: list[list[str]] = []
    has_pytest = {"value": False}

    def fake_has_pytest(python: Path) -> bool:
        return has_pytest["value"]

    def fake_install(python: Path) -> bool:
        calls.append(["install", str(python)])
        has_pytest["value"] = True  # install succeeds
        return True

    monkeypatch.setattr(sandbox, "_has_pytest", fake_has_pytest)
    monkeypatch.setattr(sandbox, "_install_pytest", fake_install)

    python = ensure_venv(tmp_path / "repo", tmp_path / "venv")

    assert calls, "expected an attempt to install pytest into the venv"
    assert python.exists()


def test_ensure_venv_falls_back_to_axon_interpreter(tmp_path, monkeypatch):
    """If the venv can't get pytest (e.g. offline) but the Axon interpreter
    has it, ensure_venv returns the Axon interpreter rather than a dead venv."""
    def fake_has_pytest(python: Path) -> bool:
        return str(python) == sys.executable

    monkeypatch.setattr(sandbox, "_has_pytest", fake_has_pytest)
    monkeypatch.setattr(sandbox, "_install_pytest", lambda python: False)

    python = ensure_venv(tmp_path / "repo", tmp_path / "venv")

    assert str(python) == sys.executable
