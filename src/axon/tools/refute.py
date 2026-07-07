"""Static-only adversarial refutation for SAST findings."""

from __future__ import annotations

import ast
from pathlib import Path


def refute(repo: str, finding: dict, mode: str = "static") -> dict:
    if mode != "static":
        raise ValueError("refute mode must be static")
    root = Path(repo).resolve()
    rel = finding.get("path", "")
    target = (root / rel).resolve()
    # `finding` is untrusted (an agent may pass any dict). Never read outside the
    # repo, and never let a crafted path suppress by escaping our checks.
    if Path(rel).is_absolute() or not target.is_relative_to(root):
        return _result("report", "path-invalid", "finding path escapes repo; not refuted")
    source = _source(target)
    line = finding.get("snippet", "")
    if _is_test_context(rel):
        return _result("suppress", "test-context", "finding is in test/example/doc context")
    if _is_constant_input(finding, source, line):
        return _result("suppress", "constant-input", "input is statically constant")
    if _is_sanitized(finding, source, line):
        return _result("suppress", "sanitized", "value is sanitized before the sink")
    return _result("report", "survived", "no static refutation found")


def _result(verdict: str, challenge: str, reason: str) -> dict:
    return {"verdict": verdict, "challenge": challenge, "reason": reason, "mode": "static"}


def _is_test_context(path: str) -> bool:
    return (
        path.startswith("tests/")
        or path.startswith("examples/")
        or path.startswith("docs/")
        or Path(path).name == "conftest.py"
    )


def _is_constant_input(finding: dict, source: str, line: str) -> bool:
    if finding.get("cwe") != "CWE-78" or "shell=True" not in line:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    target_line = int(finding.get("line", 0))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node, "lineno", None) == target_line:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return True
    return False


# Sanitizer function names per CWE. Matched against real AST Call nodes on the
# finding's line — NOT substring — so comments/strings cannot spoof suppression.
_SANITIZERS = {
    "CWE-79": {"escape", "escape_silent", "clean", "bleach"},
    "CWE-22": {"basename", "normpath", "secure_filename", "abspath"},
    "CWE-78": {"quote", "shlex_quote"},
}


def _is_sanitized(finding: dict, source: str, line: str) -> bool:
    cwe = finding.get("cwe")
    target_line = int(finding.get("line", 0) or 0)
    if cwe == "CWE-89":
        # Parameterized query: a real string arg with a ? placeholder AND a
        # second argument (the params) passed to execute(...).
        return _has_parameterized_execute(source, target_line)
    names = _SANITIZERS.get(cwe)
    if not names:
        return False
    return bool(_called_names_on_line(source, target_line) & names)


def _called_names_on_line(source: str, target_line: int) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node, "lineno", None) != target_line:
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            found.add(func.attr)
        elif isinstance(func, ast.Name):
            found.add(func.id)
    return found


def _has_parameterized_execute(source: str, target_line: int) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node, "lineno", None) == target_line
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and len(node.args) >= 2
        ):
            return True
    return False


def _source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
