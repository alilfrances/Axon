"""Runtime exception-state inspection for one pytest target."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from axon.sandbox import ensure_venv, run_in_sandbox
from axon.store import default_venv_dir


def inspect_test(repo: str, test_target: str, timeout: int = 120) -> dict:
    root = Path(repo).resolve()
    python = _python_with_pytest(root)
    axon_src = Path(__file__).resolve().parents[2]
    result = run_in_sandbox(
        [str(python), "-m", "axon._state_runner", test_target],
        root,
        timeout,
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{root}:{axon_src}"},
    )
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {
            "failures": [],
            "degraded": True,
            "note": f"state runner produced no JSON (exit {result.exit_code})",
        }
    failures = data.get("failures", [])
    exit_code = int(data.get("exit_code", result.exit_code))
    degraded = result.timed_out or (exit_code not in {0, 1} and not failures)
    note = None if not degraded else f"state runner exited {exit_code}"
    return {"failures": failures, "degraded": degraded, "note": note}


def _python_with_pytest(root: Path) -> Path:
    python = ensure_venv(root, default_venv_dir(root))
    proc = subprocess.run([str(python), "-c", "import pytest"], capture_output=True, text=True)
    if proc.returncode == 0:
        return python
    return Path(sys.executable)
