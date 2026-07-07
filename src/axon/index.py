"""Repo index: symbols + call/import edges in SQLite (.axon/index.db).

Incremental: files re-parsed only when mtime/size changes. No daemon.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .parsing import FileFacts, Parser, PythonAstParser, Symbol, iter_source_files

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    path TEXT PRIMARY KEY, mtime REAL, size INTEGER, parse_error TEXT);
CREATE TABLE IF NOT EXISTS symbols(
    id INTEGER PRIMARY KEY, name TEXT, qualname TEXT, kind TEXT,
    file TEXT, line INTEGER, end_line INTEGER);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);
CREATE TABLE IF NOT EXISTS calls(
    file TEXT, caller TEXT, callee_name TEXT);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee_name);
CREATE TABLE IF NOT EXISTS imports(file TEXT, module TEXT);
"""


class RepoIndex:
    def __init__(self, repo_root: Path, parser: Parser | None = None):
        self.repo_root = Path(repo_root).resolve()
        self.parser = parser or PythonAstParser()
        self.db_path = self.repo_root / ".axon" / "index.db"
        self.db_path.parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- build ---------------------------------------------------------------

    def refresh(self) -> dict:
        """Parse new/changed files, drop deleted ones. Returns stats."""
        seen: set[str] = set()
        parsed = 0
        for path in iter_source_files(self.repo_root, self.parser.extensions):
            rel = str(path.relative_to(self.repo_root))
            seen.add(rel)
            stat = path.stat()
            row = self.conn.execute(
                "SELECT mtime, size FROM files WHERE path=?", (rel,)
            ).fetchone()
            if row and row[0] == stat.st_mtime and row[1] == stat.st_size:
                continue
            self._store(self.parser.parse_file(path, self.repo_root), stat.st_mtime, stat.st_size)
            parsed += 1
        removed = [
            r[0] for r in self.conn.execute("SELECT path FROM files").fetchall()
            if r[0] not in seen
        ]
        for rel in removed:
            self._drop(rel)
        self.conn.commit()
        total = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return {"parsed": parsed, "removed": len(removed), "files": total}

    def _drop(self, rel: str) -> None:
        self.conn.execute("DELETE FROM symbols WHERE file=?", (rel,))
        self.conn.execute("DELETE FROM calls WHERE file=?", (rel,))
        self.conn.execute("DELETE FROM imports WHERE file=?", (rel,))
        self.conn.execute("DELETE FROM files WHERE path=?", (rel,))

    def _store(self, facts: FileFacts, mtime: float, size: int) -> None:
        self._drop(facts.file)
        self.conn.execute(
            "INSERT INTO files(path, mtime, size, parse_error) VALUES (?,?,?,?)",
            (facts.file, mtime, size, facts.parse_error),
        )
        self.conn.executemany(
            "INSERT INTO symbols(name, qualname, kind, file, line, end_line)"
            " VALUES (?,?,?,?,?,?)",
            [(s.name, s.qualname, s.kind, s.file, s.line, s.end_line)
             for s in facts.symbols],
        )
        self.conn.executemany(
            "INSERT INTO calls(file, caller, callee_name) VALUES (?,?,?)",
            [(facts.file, caller, callee) for caller, callee in facts.calls],
        )
        self.conn.executemany(
            "INSERT INTO imports(file, module) VALUES (?,?)",
            [(facts.file, m) for m in facts.imports],
        )

    # -- query ---------------------------------------------------------------

    def find_symbol(self, name: str) -> list[Symbol]:
        """Match by bare name or qualname suffix."""
        rows = self.conn.execute(
            "SELECT name, qualname, kind, file, line, end_line FROM symbols"
            " WHERE name=? OR qualname=? OR qualname LIKE ?",
            (name, name, f"%.{name}"),
        ).fetchall()
        return [Symbol(*r) for r in rows]

    def callers_of(self, name: str) -> list[dict]:
        """Call sites whose callee name matches (name-based resolution —
        dynamic dispatch makes exact resolution impossible without types)."""
        rows = self.conn.execute(
            "SELECT file, caller FROM calls WHERE callee_name=?", (name.split(".")[-1],)
        ).fetchall()
        return [{"file": f, "caller": c} for f, c in rows]

    def callees_of(self, qualname: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT callee_name FROM calls WHERE caller=?", (qualname,)
        ).fetchall()
        return [r[0] for r in rows]

    def importers_of_file(self, rel_path: str) -> list[str]:
        """Files importing the module defined by rel_path (suffix-matched)."""
        module = rel_path.removesuffix(".py").replace("/", ".")
        rows = self.conn.execute("SELECT file, module FROM imports").fetchall()
        return sorted({f for f, m in rows
                       if module == m or module.endswith("." + m) or m.endswith(module)})

    def blast_radius(self, name: str) -> list[str]:
        """Files plausibly affected if `name` changes: definition files,
        caller files, and importers of definition files."""
        out: set[str] = set()
        defs = self.find_symbol(name)
        out.update(s.file for s in defs)
        out.update(c["file"] for c in self.callers_of(name))
        for s in defs:
            out.update(self.importers_of_file(s.file))
        return sorted(out)
