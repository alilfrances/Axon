"""Composite investigation bundle for agent debugging workflows."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from axon.index import RepoIndex
from axon.providers.base import ContextProvider
from axon.tools.inspect_run import inspect_test
from axon.tools.localize import localize

_WORKFLOW = [
    "1. Read suspects + runtime state; pick the most likely function and state a one-line root-cause hypothesis.",
    "2. If no failing test exists, write one with the `repro` tool and check failure_kind matches the bug.",
    "3. If the hypothesis is unconfirmed, call `inspect` on the failing test and check the locals contradict/support it.",
    "4. Write a minimal patch for the hypothesized function only.",
    "5. Verify with `verify_fix` (single patch) or `rank_patches` (multiple candidates); only report verdicts that pass.",
]


def investigate(
    provider: ContextProvider,
    index: RepoIndex,
    repo: str,
    bug_text: str,
    failing_test: str | None = None,
    k: int = 5,
    budget_chars: int = 12000,
) -> dict:
    root = Path(repo).resolve()
    loc = localize(provider, index, bug_text, k, failing_test)
    suspects = loc["suspects"]
    runtime = inspect_test(str(root), failing_test) if failing_test else None

    top_functions: list[tuple[str, dict]] = []
    for suspect in suspects[:3]:
        for fn in suspect.get("functions", [])[:2]:
            top_functions.append((suspect["file"], fn))
    snippets = [
        snippet
        for snippet in (_snippet(root, file, fn) for file, fn in top_functions[:4])
        if snippet is not None
    ]

    graph = []
    for _, fn in top_functions[:3]:
        name = fn["qualname"].split(".")[-1]
        ctx = provider.graph_context(name)
        callers = [f'{caller["file"]}:{caller.get("caller", "?")}' for caller in ctx.callers[:5]]
        graph.append({"qualname": fn["qualname"], "callers": callers})

    result = {
        "suspects": suspects,
        "runtime": runtime,
        "snippets": snippets,
        "graph": graph,
        "recent_commits": _recent_commits(root),
        "workflow": list(_WORKFLOW),
        "truncated": False,
    }
    return _enforce_budget(result, budget_chars)


def _snippet(root: Path, file: str, fn: dict) -> dict | None:
    target = (root / file).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    start = max(int(fn["line"]) - 1, 0)
    end = min(int(fn["end_line"]), start + 40, len(lines))
    code = "\n".join(lines[start:end])
    return {"file": file, "qualname": fn["qualname"], "line": fn["line"], "code": code}


def _recent_commits(root: Path, limit: int = 5) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", f"-n{limit}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def _enforce_budget(result: dict, budget_chars: int) -> dict:
    for section in ("recent_commits", "graph", "runtime", "snippets"):
        if len(json.dumps(result)) <= budget_chars:
            break
        result[section] = [] if isinstance(result[section], list) else None
        result["truncated"] = True
    if len(json.dumps(result)) > budget_chars:
        result["suspects"] = result["suspects"][:3]
        result["truncated"] = True
    return result
