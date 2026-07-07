"""Static-only adversarial refutation for SAST findings."""

from __future__ import annotations

import ast
from pathlib import Path


def refute(repo: str, finding: dict, mode: str = "static") -> dict:
    if mode != "static":
        raise ValueError("refute mode must be static")
    root = Path(repo).resolve()
    rel = finding["path"]
    source = _source(root / rel)
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


def _is_sanitized(finding: dict, source: str, line: str) -> bool:
    cwe = finding.get("cwe")
    if cwe == "CWE-79":
        return "html.escape(" in line or ".escape(" in line
    if cwe == "CWE-22":
        return "basename(" in line or "normpath(" in line
    if cwe == "CWE-89":
        return "?" in line and "execute(" in line
    return False


def _source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
