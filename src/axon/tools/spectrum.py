"""Spectrum-based fault localization using stdlib trace."""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from axon.sandbox import ensure_venv, run_in_sandbox


def spectrum_localize(
    repo: str,
    failing_tests: list[str],
    passing_tests: list[str] | None = None,
    top: int = 20,
) -> dict:
    root = Path(repo).resolve()
    passing_tests = passing_tests or []
    try:
        failed_hits = [_trace_test(root, test) for test in failing_tests]
        passed_hits = [_trace_test(root, test) for test in passing_tests]
    except Exception as exc:
        return {"suspects": [], "degraded": True, "note": f"spectrum trace failed: {type(exc).__name__}: {exc}"}
    failed_hits = [item for item in failed_hits if item]
    passed_hits = [item for item in passed_hits if item]
    if not failed_hits:
        return {"suspects": [], "degraded": True, "note": "no failing traces collected"}
    scores = _ochiai(failed_hits, passed_hits)
    suspects = [
        {"file": file, "line": line, "score": round(score, 6), "evidence": ["spectrum ochiai"]}
        for (file, line), score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top]
    ]
    return {"suspects": suspects, "degraded": False, "note": "stdlib trace spectrum"}


def _trace_test(repo: Path, test_id: str) -> dict[tuple[str, int], bool]:
    python = ensure_venv(repo, repo / ".axon" / "venv")
    result = run_in_sandbox(
        [str(python), "-m", "axon._trace_runner", test_id],
        repo,
        30,
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{repo}:{Path(__file__).resolve().parents[2]}"},
    )
    stderr = result.stderr.lower()
    if "not found" in stderr or "no tests ran" in stderr:
        return {}
    try:
        raw = result.stdout.strip().splitlines()[-1]
        data = json.loads(raw)
    except (IndexError, json.JSONDecodeError):
        return {}
    return {
        (file, int(line)): True
        for file, lines in data.items()
        for line in lines
        if _interesting(file)
    }


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
