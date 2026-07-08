"""Source parsing behind a small interface.

v0 ships PythonAstParser (stdlib ast, zero deps). A tree-sitter backend can
implement the same Parser protocol at the multi-lang milestone.
"""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol


@dataclass(frozen=True)
class Symbol:
    name: str
    qualname: str
    kind: str  # "function" | "class" | "method"
    file: str
    line: int
    end_line: int


@dataclass
class FileFacts:
    file: str
    symbols: list[Symbol] = field(default_factory=list)
    # (caller_qualname, callee_name) — callee unresolved at parse time
    calls: list[tuple[str, str]] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    parse_error: str | None = None


class Parser(Protocol):
    extensions: tuple[str, ...]

    def parse_file(self, path: Path, repo_root: Path) -> FileFacts:
        pass


class PythonAstParser:
    extensions = (".py",)

    def parse_file(self, path: Path, repo_root: Path) -> FileFacts:
        rel = str(path.relative_to(repo_root))
        facts = FileFacts(file=rel)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            facts.parse_error = f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
            return facts
        _Visitor(rel, facts).visit(tree)
        return facts


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel_file: str, facts: FileFacts):
        self.file = rel_file
        self.facts = facts
        self.scope: list[str] = []

    def _qual(self, name: str) -> str:
        return ".".join([*self.scope, name])

    def _add_symbol(self, node: ast.AST, name: str, kind: str) -> None:
        self.facts.symbols.append(
            Symbol(
                name=name,
                qualname=self._qual(name),
                kind=kind,
                file=self.file,
                line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        self.facts.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.level == 0:
            self.facts.imports.append(node.module)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add_symbol(node, node.name, "class")
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "method" if self.scope else "function"
        self._add_symbol(node, node.name, kind)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def visit_Call(self, node: ast.Call) -> None:
        callee = _call_name(node.func)
        if callee:
            caller = ".".join(self.scope) if self.scope else "<module>"
            self.facts.calls.append((caller, callee))
        self.generic_visit(node)


def _call_name(func: ast.expr) -> str | None:
    # foo(...) -> "foo"; obj.foo(...) -> "foo" (attribute base is dynamic;
    # resolution happens against the symbol table at index time)
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# Directories that never hold first-party source: VCS metadata, virtualenvs,
# dependency checkouts, and build output. Skipping them keeps the index off
# vendored/generated files (e.g. CMake's _deps/googletest-src) that otherwise
# dominate retrieval on large native repos.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".axon", ".tox", ".eggs", ".nox", "build", "dist",
    "_deps", "target", "out", "coverage", "htmlcov", "site-packages",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
}
# Prefix-matched skips for directories whose exact name varies by build config.
_SKIP_DIR_PREFIXES = ("cmake-build", "cmake_build")


def _is_skipped_dir(name: str) -> bool:
    return name in _SKIP_DIRS or name.startswith(_SKIP_DIR_PREFIXES)


def iter_source_files(repo_root: Path, extensions: Iterable[str]) -> list[Path]:
    repo_root = Path(repo_root)
    exts = tuple(extensions)
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Prune skipped directories in place so os.walk never descends into them.
        dirnames[:] = [d for d in dirnames if not _is_skipped_dir(d)]
        base = Path(dirpath)
        for name in filenames:
            if name.endswith(exts):
                out.append(base / name)
    ignored = _git_ignored(repo_root, out)
    return sorted(p for p in out if p not in ignored)


def _git_ignored(repo_root: Path, paths: list[Path]) -> set[Path]:
    """Paths git ignores (honors .gitignore, .git/info/exclude, global excludes).

    Best-effort: returns an empty set when the repo is not a git checkout or
    git is unavailable, so indexing degrades to the static skip list only.
    """
    if not paths or not (repo_root / ".git").exists():
        return set()
    rels = [str(p.relative_to(repo_root)) for p in paths]
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=str(repo_root),
            input="\n".join(rels),
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if proc.returncode not in (0, 1):  # 0: some ignored, 1: none ignored
        return set()
    return {repo_root / line for line in proc.stdout.splitlines() if line.strip()}
