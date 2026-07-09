"""Run a repo's test suite through Axon's sandbox helper."""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

from axon.parsing import _is_skipped_dir
from axon.sandbox import ensure_venv, run_in_sandbox
from axon.store import default_venv_dir

_SUMMARY_RE = re.compile(r"(?P<count>\d+)\s+(?P<kind>failed|passed|error|errors)")
_FAIL_RE = re.compile(r"^(FAILED|ERROR)\s+(?P<test>\S+)\s+-\s+(?P<msg>.*)$")
_CTEST_SUMMARY_RE = re.compile(
    r"(?P<passed_pct>\d+)% tests passed,\s+(?P<failed>\d+) tests failed out of (?P<total>\d+)"
)
_CTEST_FAIL_RE = re.compile(r"^\s*\d+\s+-\s+(?P<test>.+?)\s+\((?P<msg>[^)]+)\)")


def detect_test_runner(repo: Path) -> dict:
    repo = Path(repo).resolve()
    build_dir = _find_ctest_build_dir(repo)
    has_cmake_tests = _has_cmake_tests(repo)
    has_pytest = _has_pytest_project(repo)
    if build_dir is not None or (has_cmake_tests and not has_pytest):
        return {
            "kind": "ctest",
            "build_dir": str(build_dir) if build_dir else None,
            "reason": "CTestTestfile.cmake" if build_dir else "CMakeLists.txt declares tests",
        }
    return {"kind": "pytest", "build_dir": None, "reason": "pytest project markers" if has_pytest else "default"}


def run_test_suite(repo: Path, test_target: str | None = None, timeout_s: int = 120) -> dict:
    repo = Path(repo).resolve()
    runner = detect_test_runner(repo)
    if runner["kind"] == "ctest":
        return _run_ctest(repo, runner, test_target, timeout_s)
    return _run_pytest(repo, test_target, timeout_s)


def _run_pytest(repo: Path, test_target: str | None, timeout_s: int) -> dict:
    python = ensure_venv(repo, default_venv_dir(repo))
    cmd = [str(python), "-m", "pytest", "-q", "--tb=line"]
    if test_target:
        cmd.append(test_target)
    result = run_in_sandbox(cmd, repo, timeout_s)
    parsed = _parse_result(result.stdout + result.stderr, result.exit_code, result.timed_out, result.duration_s)
    parsed["runner"] = "pytest"
    return parsed


def _run_ctest(repo: Path, runner: dict, test_target: str | None, timeout_s: int) -> dict:
    build_dir = Path(runner["build_dir"]).resolve() if runner.get("build_dir") else None
    if build_dir is None:
        return _empty_result(
            1,
            False,
            0.0,
            "ctest",
            "CMake tests detected, but no CTestTestfile.cmake build directory was found",
        )
    junit = build_dir / ".axon_ctest_results.xml"
    cmd = ["ctest", "--test-dir", str(build_dir), "--output-on-failure", "--output-junit", str(junit)]
    if test_target:
        cmd.extend(["-R", test_target])
    result = run_in_sandbox(cmd, repo, timeout_s)
    output = result.stdout + result.stderr
    parsed = _parse_ctest_junit(junit, result.exit_code, result.timed_out, result.duration_s)
    if parsed is None:
        parsed = _parse_ctest_text(output, result.exit_code, result.timed_out, result.duration_s)
    parsed["runner"] = "ctest"
    parsed["build_dir"] = str(build_dir)
    parsed["raw_tail"] = "\n".join(output.splitlines()[-40:])
    if result.exit_code == 127:
        parsed["note"] = "ctest executable not found"
    return parsed


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
            elif kind in {"error", "errors"}:
                errors = count
        fail = _FAIL_RE.match(line)
        if fail:
            failures.append({"test_id": fail.group("test"), "message": fail.group("msg")})
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "failures": failures[:20],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "raw_tail": "\n".join(output.splitlines()[-40:]),
    }


def _parse_ctest_junit(path: Path, exit_code: int, timed_out: bool, duration_s: float) -> dict | None:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    cases = list(root.iter("testcase"))
    failures: list[dict] = []
    errors = 0
    for case in cases:
        test_id = case.attrib.get("name") or case.attrib.get("classname") or "<unknown>"
        failure = case.find("failure")
        error = case.find("error")
        if failure is not None:
            failures.append({"test_id": test_id, "message": failure.attrib.get("message", "") or (failure.text or "")[:200]})
        elif error is not None:
            errors += 1
            failures.append({"test_id": test_id, "message": error.attrib.get("message", "") or (error.text or "")[:200]})
    failed = len(failures) - errors
    return {
        "passed": max(0, len(cases) - len(failures)),
        "failed": failed,
        "errors": errors,
        "failures": failures[:20],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "raw_tail": "",
    }


def _parse_ctest_text(output: str, exit_code: int, timed_out: bool, duration_s: float) -> dict:
    total = failed = 0
    failures: list[dict] = []
    for line in output.splitlines():
        summary = _CTEST_SUMMARY_RE.search(line)
        if summary:
            total = int(summary.group("total"))
            failed = int(summary.group("failed"))
        fail = _CTEST_FAIL_RE.match(line)
        if fail:
            failures.append({"test_id": fail.group("test"), "message": fail.group("msg")})
    if failed and not failures:
        failures.append({"test_id": "ctest", "message": "one or more CTest tests failed"})
    return {
        "passed": max(0, total - failed),
        "failed": failed,
        "errors": 0,
        "failures": failures[:20],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "raw_tail": "\n".join(output.splitlines()[-40:]),
    }


def _empty_result(exit_code: int, timed_out: bool, duration_s: float, runner: str, note: str) -> dict:
    return {
        "passed": 0,
        "failed": 0,
        "errors": 1 if exit_code else 0,
        "failures": [{"test_id": runner, "message": note}] if exit_code else [],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "raw_tail": note,
        "runner": runner,
        "note": note,
    }


def _find_ctest_build_dir(repo: Path) -> Path | None:
    candidates = [
        repo / "build",
        repo / "cmake-build-debug",
        repo / "cmake-build-release",
        repo / "out" / "build",
        repo,
    ]
    for candidate in candidates:
        if (candidate / "CTestTestfile.cmake").exists():
            return candidate
    fallback: list[Path] = []
    for path in repo.rglob("CTestTestfile.cmake"):
        parts = path.relative_to(repo).parts
        if any(part.startswith(".") or _is_skipped_dir(part) for part in parts):
            continue
        fallback.append(path.parent)
    if fallback:
        return min(fallback, key=lambda path: (len(path.relative_to(repo).parts), str(path)))
    return None


def _has_cmake_tests(repo: Path) -> bool:
    cmake = repo / "CMakeLists.txt"
    try:
        text = cmake.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "enable_testing" in text or "add_test" in text


def _has_pytest_project(repo: Path) -> bool:
    if (repo / "pytest.ini").exists() or (repo / "conftest.py").exists():
        return True
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            if "[tool.pytest" in pyproject.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            pass
    return any(path.name.startswith("test_") and path.suffix == ".py" for path in repo.rglob("*.py"))
