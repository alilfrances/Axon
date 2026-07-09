"""Repro test scaffold tool."""

from __future__ import annotations

import re
from pathlib import Path

from axon.tools.run_tests import detect_test_runner, run_test_suite

_SLUG_RE = re.compile(r"[^a-z0-9_]+")
_EXC_LINE_RE = re.compile(r"\b([A-Za-z_]\w*(?:Error|Exception))\b")


def repro_scaffold(repo: str, bug_slug: str, test_body: str | None = None) -> dict:
    root = Path(repo).resolve()
    slug = _sanitize(bug_slug)
    runner = detect_test_runner(root)
    body = test_body if test_body is not None else _skeleton(slug, runner["kind"])
    valid, expected = _valid_body(body, runner["kind"])
    if not valid:
        return {"created": False, "error": f"test_body must contain {expected}", "path": None}
    target = _target_path(root, slug, runner["kind"])
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_gitignored(root, target.parent)
    target.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    rel = str(target.relative_to(root))
    test_target = rel if runner["kind"] == "pytest" else slug
    result = run_test_suite(root, test_target)
    return {
        "created": True,
        "path": str(target),
        "test_target": test_target,
        "runner": runner["kind"],
        "currently_fails": result["failed"] > 0 or result["errors"] > 0 or result["exit_code"] != 0,
        "failure_kind": _classify(result),
        "failure_excerpt": _excerpt(result),
        "test_result": result,
    }


def _ensure_gitignored(root: Path, dir_path: Path) -> None:
    """Keep generated repro tests out of git. A directory-local .gitignore of
    ``*`` hides every file here (including itself), so `git status` stays clean
    while the scaffolds remain runnable by pytest."""
    ignore = dir_path / ".gitignore"
    if not ignore.exists():
        ignore.write_text(
            "# Axon repro scaffolds - generated, not for version control.\n*\n",
            encoding="utf-8",
        )
    _ensure_git_info_excludes(root, dir_path)


def _ensure_git_info_excludes(root: Path, dir_path: Path) -> None:
    exclude = root / ".git" / "info" / "exclude"
    if not exclude.parent.exists():
        return
    rel = dir_path.relative_to(root).as_posix().rstrip("/") + "/"
    try:
        existing = exclude.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    if rel not in {line.strip() for line in existing.splitlines()}:
        prefix = "" if existing.endswith("\n") or not existing else "\n"
        exclude.write_text(f"{existing}{prefix}{rel}\n", encoding="utf-8")


def _sanitize(slug: str) -> str:
    value = _SLUG_RE.sub("_", slug.lower()).strip("_")
    return value or "bug"


def _target_path(root: Path, slug: str, runner: str) -> Path:
    suffix = ".py" if runner == "pytest" else ".cpp"
    prefix = "test_" if runner == "pytest" else "repro_"
    base = root / "tests" / "repros" / f"{prefix}{slug}{suffix}"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = root / "tests" / "repros" / f"{prefix}{slug}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _skeleton(slug: str, runner: str) -> str:
    if runner == "ctest":
        return (
            "#include <gtest/gtest.h>\n\n"
            "// TODO: wire this file into CMakeLists.txt with add_executable/add_test.\n"
            f"TEST(AxonRepro, {slug}) {{\n"
            "    FAIL() << \"repro not implemented\";\n"
            "}\n"
        )
    return (
        "import pytest\n\n\n"
        f"def test_{slug}_repro():\n"
        "    # TODO: replace with a concrete reproduction.\n"
        "    pytest.fail(\"repro not implemented\")\n"
    )


def _valid_body(body: str, runner: str) -> tuple[bool, str]:
    if runner == "ctest":
        return ("TEST(" in body or "TEST_F(" in body, "TEST(...) or TEST_F(...)")
    return ("def test_" in body, "def test_")


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
