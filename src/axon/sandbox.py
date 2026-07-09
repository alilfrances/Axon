"""Process sandbox helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import venv
from dataclasses import dataclass
from pathlib import Path

_CAP = 200_000


@dataclass(frozen=True)
class SandboxResult:
    cmd: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool


def run_in_sandbox(
    cmd: list[str],
    cwd: Path,
    timeout_s: int = 60,
    env_extra: dict | None = None,
) -> SandboxResult:
    env = os.environ.copy()
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
        duration = time.monotonic() - start
        return SandboxResult(cmd, str(cwd), proc.returncode, _cap(proc.stdout), _cap(proc.stderr), duration, False)
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        return SandboxResult(
            cmd,
            str(cwd),
            -9,
            _cap(exc.stdout or ""),
            _cap(exc.stderr or ""),
            duration,
            True,
        )
    except OSError as exc:
        duration = time.monotonic() - start
        return SandboxResult(cmd, str(cwd), 127, "", _cap(str(exc)), duration, False)


def ensure_venv(repo: Path, path: Path) -> Path:
    """Create an ephemeral Python venv, best-effort editable-install the repo,
    and return an interpreter that can run pytest.

    The sandbox venv rarely ships pytest, so install it there when missing; if
    that can't happen (e.g. offline) fall back to the interpreter running Axon
    when it has pytest, rather than leaving test tooling silently dead.
    """
    repo = Path(repo).resolve()
    path = Path(path).resolve()
    python = path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True).create(path)
    if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", str(repo)],
            cwd=str(repo),
            text=True,
            capture_output=True,
            timeout=120,
        )
    if not python.exists():
        return Path(sys.executable)
    if _has_pytest(python) or (_install_pytest(python) and _has_pytest(python)):
        return python
    if _has_pytest(Path(sys.executable)):
        return Path(sys.executable)
    return python


def _has_pytest(python: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python), "-m", "pytest", "--version"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _install_pytest(python: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "pytest"],
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _cap(text: str | bytes) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= _CAP:
        return text
    return text[:_CAP] + "\n[axon: output truncated]"
