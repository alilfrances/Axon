"""Run a repo's pytest suite through Axon's sandbox helper."""

from __future__ import annotations

import re
from pathlib import Path

from axon.sandbox import ensure_venv, run_in_sandbox
from axon.store import default_venv_dir

_SUMMARY_RE = re.compile(r"(?P<count>\d+)\s+(?P<kind>failed|passed|error|errors)")
_FAIL_RE = re.compile(r"^(FAILED|ERROR)\s+(?P<test>\S+)\s+-\s+(?P<msg>.*)$")


def run_test_suite(repo: Path, test_target: str | None = None, timeout_s: int = 120) -> dict:
    repo = Path(repo).resolve()
    python = ensure_venv(repo, default_venv_dir(repo))
    cmd = [str(python), "-m", "pytest", "-q", "--tb=line"]
    if test_target:
        cmd.append(test_target)
    result = run_in_sandbox(cmd, repo, timeout_s)
    return _parse_result(result.stdout + result.stderr, result.exit_code, result.timed_out, result.duration_s)


def _parse_result(output: str, exit_code: int, timed_out: bool, duration_s: float) -> dict:
    passed = failed = errors = 0
    failures: list[dict] = []
    for line in output.splitlines():
        for match in _SUMMARY_RE.finditer(line):
            count = int(match.group("count"))
            kind = match.group("kind")
            if kind == "passed":
                passed = count
            elif kind == "failed":
                failed = count
            else:
                errors = count
        fail = _FAIL_RE.match(line.strip())
        if fail:
            failures.append({"test_id": fail.group("test"), "message": fail.group("msg")})
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "failures": failures,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "raw_tail": output[-2000:],
    }
