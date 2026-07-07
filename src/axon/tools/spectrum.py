"""Spectrum-based fault localization using stdlib trace."""

from __future__ import annotations

import json
import math
import sys
import ast
import subprocess
from pathlib import Path

from axon.index import RepoIndex
from axon.sandbox import ensure_venv, run_in_sandbox
from axon.store import default_venv_dir


def spectrum_localize(
    repo: str,
    failing_tests: list[str],
    passing_tests: list[str] | None = None,
    top: int = 20,
) -> dict:
    root = Path(repo).resolve()
    passing_used = passing_tests or _auto_passing_tests(root, failing_tests)
    try:
        failed_traces = [_trace_test(root, test) for test in failing_tests]
        passed_traces = [_trace_test(root, test) for test in passing_used]
    except Exception as exc:
        return {"suspects": [], "degraded": True, "note": f"spectrum trace failed: {type(exc).__name__}: {exc}"}
    failed_hits = [hits for hits, code in failed_traces if hits and code != 0]
    passed_hits = [hits for hits, code in passed_traces if hits and code == 0]
    if not failed_hits:
        return {"suspects": [], "degraded": True, "note": "no failing traces collected"}
    scores = _ochiai(failed_hits, passed_hits)
    suspects = [
        {"file": file, "line": line, "score": round(score, 6), "evidence": ["spectrum ochiai"]}
        for (file, line), score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top]
    ]
    functions = _function_scores(root, scores, top)
    return {
        "suspects": suspects,
        "functions": functions,
        "passing_used": passing_used,
        "degraded": False,
        "note": "stdlib trace spectrum",
    }


def _trace_test(repo: Path, test_id: str) -> tuple[dict[tuple[str, int], bool], int]:
    python = _python_with_pytest(repo)
    result = run_in_sandbox(
        [str(python), "-m", "axon._trace_runner", test_id],
        repo,
        30,
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{repo}:{Path(__file__).resolve().parents[2]}"},
    )
    stderr = result.stderr.lower()
    if "not found" in stderr or "no tests ran" in stderr:
        return {}, result.exit_code
    try:
        raw = result.stdout.strip().splitlines()[-1]
        data = json.loads(raw)
    except (IndexError, json.JSONDecodeError):
        return {}, result.exit_code
    if isinstance(data, dict) and "lines" in data:
        lines_by_file = data.get("lines", {})
        exit_code = int(data.get("exit_code", result.exit_code))
    else:
        lines_by_file = data
        exit_code = result.exit_code
    return {
        (file, int(line)): True
        for file, lines in lines_by_file.items()
        for line in lines
        if _interesting(file)
    }, exit_code


def _ochiai(failed_hits: list[dict], passed_hits: list[dict]) -> dict[tuple[str, int], float]:
    total_failed = len(failed_hits)
    all_lines = set().union(*(set(hit) for hit in failed_hits), *(set(hit) for hit in passed_hits))
    scores: dict[tuple[str, int], float] = {}
    for line in all_lines:
        ef = sum(1 for hit in failed_hits if line in hit)
        ep = sum(1 for hit in passed_hits if line in hit)
        if ef == 0:
            continue
        scores[line] = ef / math.sqrt(total_failed * (ef + ep))
    return scores


def _interesting(file: str) -> bool:
    return file.endswith(".py") and not file.startswith("tests/")


def _python_with_pytest(repo: Path) -> Path:
    python = ensure_venv(repo, default_venv_dir(repo))
    proc = subprocess.run([str(python), "-c", "import pytest"], capture_output=True, text=True)
    if proc.returncode == 0:
        return python
    return Path(sys.executable)


def _auto_passing_tests(repo: Path, failing_tests: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set(failing_tests)
    for test_id in failing_tests:
        file = test_id.split("::", 1)[0]
        path = repo / file
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except OSError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                candidate = f"{file}::{node.name}"
                if candidate not in seen:
                    out.append(candidate)
                    seen.add(candidate)
    return out


def _function_scores(root: Path, line_scores: dict[tuple[str, int], float], top: int) -> list[dict]:
    index = RepoIndex(root)
    try:
        index.refresh()
        scored: dict[tuple[str, str], dict] = {}
        for (file, line), score in line_scores.items():
            row = index.conn.execute(
                "SELECT qualname, line, end_line FROM symbols"
                " WHERE file=? AND kind IN ('function','method') AND line<=? AND end_line>=?"
                " ORDER BY line DESC LIMIT 1",
                (file, line, line),
            ).fetchone()
            if row is None:
                continue
            qualname, fn_line, fn_end = row
            entry = scored.setdefault(
                (file, qualname),
                {"file": file, "qualname": qualname, "line": fn_line, "end_line": fn_end, "score": 0.0},
            )
            entry["score"] += score
        functions = sorted(scored.values(), key=lambda fn: (-fn["score"], fn["file"], fn["qualname"]))[:top]
        for fn in functions:
            fn["score"] = round(fn["score"], 6)
        return functions
    finally:
        index.close()
