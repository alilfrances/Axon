"""Apply a candidate patch, verify it, and always restore the worktree."""

from __future__ import annotations

import subprocess
import re
import sys
from pathlib import Path

from axon.sandbox import ensure_venv, run_in_sandbox
from axon.store import default_venv_dir
from axon.tools.run_tests import _parse_result


def verify_fix(
    repo: str,
    patch: str,
    repro_test: str,
    timeout: int = 600,
    keep: bool = False,
) -> dict:
    root = Path(repo).resolve()
    repro_before = _run_pytest(root, repro_test, timeout)
    if _passed(repro_before):
        return {
            "verdict": "repro-not-red",
            "repro_before": repro_before,
            "repro_after": None,
            "regressions": [],
            "applied": False,
            "reverted": False,
            "method": None,
        }
    baseline = _run_pytest(root, None, timeout)
    applied = False
    method = "git" if _is_git_repo(root) else "fallback"
    apply_result: dict | None = None
    try:
        apply_result = _apply_patch(root, patch, method)
        if apply_result["exit_code"] != 0:
            return {
                "verdict": "apply-failed",
                "error": apply_result["stderr"] or apply_result["stdout"],
                "repro_before": repro_before,
                "repro_after": None,
                "regressions": [],
                "applied": False,
                "reverted": False,
                "method": method,
            }
        applied = True
        repro_after = _run_pytest(root, repro_test, timeout)
        full_after = _run_pytest(root, None, timeout)
        regressions = sorted(_failure_ids(full_after) - _failure_ids(baseline))
        if not _passed(repro_after):
            verdict = "fix-does-not-fix"
        elif regressions:
            verdict = "regressions"
        else:
            verdict = "pass"
        return {
            "verdict": verdict,
            "repro_before": repro_before,
            "repro_after": repro_after,
            "regressions": regressions,
            "applied": True,
            "reverted": keep is False,
            "method": method,
        }
    finally:
        if applied and not keep:
            _revert_patch(root, patch, method, apply_result)


def _run_pytest(repo: Path, target: str | None, timeout: int) -> dict:
    python = _python_with_pytest(repo)
    cmd = [str(python), "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider"]
    if target:
        cmd.append(target)
    result = run_in_sandbox(
        cmd,
        repo,
        timeout,
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(repo)},
    )
    return _parse_result(result.stdout + result.stderr, result.exit_code, result.timed_out, result.duration_s)


def _python_with_pytest(repo: Path) -> Path:
    python = ensure_venv(repo, default_venv_dir(repo))
    proc = subprocess.run([str(python), "-c", "import pytest"], capture_output=True, text=True)
    if proc.returncode == 0:
        return python
    return Path(sys.executable)


def _is_git_repo(repo: Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo, capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _apply_patch(repo: Path, patch: str, method: str) -> dict:
    if method == "git":
        return _git_apply(repo, patch, reverse=False)
    return _fallback_apply(repo, patch)


def _revert_patch(repo: Path, patch: str, method: str, apply_result: dict | None) -> None:
    if method == "git":
        _git_apply(repo, patch, reverse=True)
        return
    for rel, content in (apply_result or {}).get("backups", {}).items():
        (repo / rel).write_text(content, encoding="utf-8")


def _git_apply(repo: Path, patch: str, reverse: bool) -> dict:
    cmd = ["git", "apply"]
    if reverse:
        cmd.append("-R")
    proc = subprocess.run(cmd, cwd=repo, input=patch, text=True, capture_output=True)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _fallback_apply(repo: Path, patch: str) -> dict:
    parsed = _parse_single_file_patch(patch)
    if parsed is None:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": "fallback patch apply supports only simple single-file unified diffs",
        }
    rel, hunks = parsed
    path = repo / rel
    try:
        original = path.read_text(encoding="utf-8")
        patched = _apply_hunks(original.splitlines(keepends=True), hunks)
    except (OSError, ValueError) as exc:
        return {"exit_code": 1, "stdout": "", "stderr": str(exc)}
    path.write_text("".join(patched), encoding="utf-8")
    return {"exit_code": 0, "stdout": "", "stderr": "", "backups": {rel: original}}


def _parse_single_file_patch(patch: str) -> tuple[str, list[tuple[int, list[str]]]] | None:
    lines = patch.splitlines(keepends=True)
    old_files = [line[6:].strip() for line in lines if line.startswith("--- ")]
    new_files = [line[6:].strip() for line in lines if line.startswith("+++ ")]
    if len(old_files) != 1 or len(new_files) != 1:
        return None
    old = old_files[0].removeprefix("a/")
    new = new_files[0].removeprefix("b/")
    if old != new or old == "/dev/null" or new == "/dev/null":
        return None
    hunks: list[tuple[int, list[str]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
        if not match:
            index += 1
            continue
        start = int(match.group(1))
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("@@ "):
            body.append(lines[index])
            index += 1
        hunks.append((start, body))
    return (new, hunks) if hunks else None


def _apply_hunks(original: list[str], hunks: list[tuple[int, list[str]]]) -> list[str]:
    out: list[str] = []
    pos = 0
    for start, body in hunks:
        hunk_pos = start - 1
        if hunk_pos < pos:
            raise ValueError("overlapping hunks")
        out.extend(original[pos:hunk_pos])
        pos = hunk_pos
        for raw in body:
            if raw.startswith("\\"):
                continue
            prefix, text = raw[0], raw[1:]
            if prefix == " ":
                _assert_line(original, pos, text)
                out.append(original[pos])
                pos += 1
            elif prefix == "-":
                _assert_line(original, pos, text)
                pos += 1
            elif prefix == "+":
                out.append(text)
            else:
                raise ValueError("invalid unified diff line")
    out.extend(original[pos:])
    return out


def _assert_line(original: list[str], pos: int, expected: str) -> None:
    if pos >= len(original) or original[pos] != expected:
        raise ValueError("patch context does not match")


def _passed(result: dict) -> bool:
    return result["exit_code"] == 0 and not result["timed_out"] and result["failed"] == 0 and result["errors"] == 0


def _failure_ids(result: dict) -> set[str]:
    return {item["test_id"] for item in result.get("failures", [])}
