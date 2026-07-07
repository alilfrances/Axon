"""Offline SAST scan over bundled Axon Python rules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

_RULES = [
    ("axon.python.cwe-78.subprocess-shell-true", "CWE-78", "ERROR", "subprocess with shell=True", re.compile(r"subprocess\.(?:run|call|Popen)\(.*shell\s*=\s*True")),
    ("axon.python.cwe-89.sql-string-format", "CWE-89", "ERROR", "SQL query built with string formatting", re.compile(r"(?:execute\(f[\"']|SELECT .*\\{|\bsql\s*=\s*f[\"'])", re.I)),
    ("axon.python.cwe-79.html-fstring", "CWE-79", "WARNING", "HTML f-string output", re.compile(r"f[\"'].*<[^>]+>.*\{.*\}.*[\"']")),
    ("axon.python.cwe-22.path-join-open", "CWE-22", "ERROR", "open over joined path", re.compile(r"open\(os\.path\.join\(")),
    ("axon.python.cwe-502.pickle-loads", "CWE-502", "ERROR", "pickle deserialization", re.compile(r"pickle\.loads?\(")),
    ("axon.python.cwe-327.weak-md5", "CWE-327", "WARNING", "weak MD5 hashing", re.compile(r"hashlib\.md5\(")),
    ("axon.python.cwe-798.hardcoded-secret", "CWE-798", "ERROR", "hardcoded secret-like value", re.compile(r"(?i)(secret|token|api[_-]?key)\s*=\s*[\"'][^\"']{8,}[\"']")),
]


def bundled_rules_path() -> Path:
    return Path(resources.files("axon").joinpath("rules", "axon_python.yml"))


def sast_scan(repo: str, timeout: int = 60) -> dict:
    root = Path(repo).resolve()
    config = bundled_rules_path()
    semgrep = _semgrep_binary()
    command = [semgrep or "semgrep", "--config", str(config), "--json", "--metrics=off", str(root)]
    start = time.monotonic()
    semgrep_error = None
    findings: list[dict]
    backend = "semgrep"
    if semgrep:
        try:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout,
                env={**os.environ, "SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"},
            )
            if proc.returncode in (0, 1) and proc.stdout.strip():
                findings = _parse_semgrep(root, proc.stdout)
            else:
                semgrep_error = (proc.stderr or proc.stdout).strip()
                findings = _fallback_scan(root)
                backend = "python-fallback"
        except Exception as exc:
            semgrep_error = f"{type(exc).__name__}: {exc}"
            findings = _fallback_scan(root)
            backend = "python-fallback"
    else:
        findings = _fallback_scan(root)
        backend = "python-fallback"
    return {
        "findings": findings,
        "count": len(findings),
        "repo": str(root),
        "config": str(config),
        "command": command,
        "backend": backend,
        "semgrep_available": semgrep is not None,
        "semgrep_error": semgrep_error,
        "duration_s": time.monotonic() - start,
    }


def _semgrep_binary() -> str | None:
    local = Path(sys.prefix) / "bin" / "semgrep"
    if local.exists():
        return str(local)
    return shutil.which("semgrep")


def _parse_semgrep(root: Path, raw: str) -> list[dict]:
    data = json.loads(raw)
    findings = []
    for item in data.get("results", []):
        path = Path(item["path"])
        rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
        if _excluded(rel):
            continue
        extra = item.get("extra", {})
        line = int(item.get("start", {}).get("line", 1))
        end_line = int(item.get("end", {}).get("line", line))
        snippet = extra.get("lines", "").strip()
        # Semgrep returns the literal placeholder "requires login" in extra.lines
        # when it cannot re-read the source; fall back to reading it ourselves so
        # snippets (and any inline markers) are always faithful.
        if not snippet or snippet == "requires login":
            snippet = _read_source(root, rel, line, end_line)
        rule_id = item.get("check_id", "")
        cwe = extra.get("metadata", {}).get("cwe") or _cwe_from_id(rule_id)
        findings.append(_finding(rule_id, cwe, extra.get("severity", "WARNING"), rel, line, extra.get("message", ""), snippet))
    return findings


def _fallback_scan(root: Path) -> list[dict]:
    findings = []
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        if _excluded(rel):
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for rule_id, cwe, severity, message, pattern in _RULES:
                if pattern.search(line):
                    findings.append(_finding(rule_id, cwe, severity, rel, line_no, message, line.strip()))
    return findings


def _read_source(root: Path, rel: str, line: int, end_line: int) -> str:
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[line - 1:end_line]).strip()


def _finding(rule_id: str, cwe: str, severity: str, path: str, line: int, message: str, snippet: str) -> dict:
    fp = hashlib.sha1(f"{rule_id}:{path}:{line}:{snippet}".encode("utf-8")).hexdigest()
    return {
        "id": rule_id,
        "cwe": cwe,
        "severity": severity,
        "path": path,
        "line": line,
        "message": message,
        "snippet": snippet,
        "fingerprint": fp,
    }


def _cwe_from_id(rule_id: str) -> str:
    match = re.search(r"cwe-(\d+)", rule_id)
    return f"CWE-{match.group(1)}" if match else "CWE-unknown"


def _excluded(rel: str) -> bool:
    return rel.startswith(".axon/") or rel.startswith("tests/axon_repro/")
