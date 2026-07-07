"""Repro test scaffold tool."""

from __future__ import annotations

import re
from pathlib import Path

from axon.sandbox import ensure_venv
from axon.tools.run_tests import run_test_suite

_SLUG_RE = re.compile(r"[^a-z0-9_]+")
_EXC_LINE_RE = re.compile(r"\b([A-Za-z_]\w*(?:Error|Exception))\b")


def repro_scaffold(repo: str, bug_slug: str, test_body: str | None = None) -> dict:
    root = Path(repo).resolve()
    slug = _sanitize(bug_slug)
    body = test_body if test_body is not None else _skeleton(slug)
    if "def test_" not in body:
        return {"created": False, "error": "test_body must contain def test_", "path": None}
    target = _target_path(root, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    rel = str(target.relative_to(root))
    result = run_test_suite(root, rel)
    return {
        "created": True,
        "path": str(target),
        "test_target": rel,
        "currently_fails": result["failed"] > 0 or result["errors"] > 0 or result["exit_code"] != 0,
        "failure_kind": _classify(result),
        "failure_excerpt": _excerpt(result),
        "test_result": result,
    }


def _sanitize(slug: str) -> str:
    value = _SLUG_RE.sub("_", slug.lower()).strip("_")
    return value or "bug"


def _target_path(root: Path, slug: str) -> Path:
    base = root / "tests" / "repros" / f"test_{slug}.py"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = root / "tests" / "repros" / f"test_{slug}_{index}.py"
        if not candidate.exists():
            return candidate
        index += 1


def _skeleton(slug: str) -> str:
    return (
        "import pytest\n\n\n"
        f"def test_{slug}_repro():\n"
        "    # TODO: replace with a concrete reproduction.\n"
        "    pytest.fail(\"repro not implemented\")\n"
    )


def _classify(result: dict) -> str:
    if result.get("timed_out"):
        return "timeout"
    if result["exit_code"] == 0 and result["failed"] == 0 and result["errors"] == 0:
        return "passes"
    tail = result.get("raw_tail", "")
    if "errors during collection" in tail or "collected 0 items" in tail:
        return "collection-error"
    if "AssertionError" in tail or re.search(r"^E?\s*assert\b", tail, re.MULTILINE):
        return "assertion"
    exc_names = [m for m in _EXC_LINE_RE.findall(tail) if m != "AssertionError"]
    if exc_names:
        return f"exception:{exc_names[-1]}"
    return "unknown"


def _excerpt(result: dict) -> str:
    lines = [line for line in result.get("raw_tail", "").splitlines() if line.strip()]
    return "\n".join(lines[-15:])
