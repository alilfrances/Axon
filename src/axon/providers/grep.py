"""Last-resort grep context provider."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .base import GraphContext, SearchHit


class GrepProvider:
    backend = "grep"

    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()

    def index(self, repo: Path) -> dict:
        self.repo = Path(repo).resolve()
        files = list(self.repo.rglob("*.py"))
        return {"files": len(files), "parsed": 0, "removed": 0, "degraded": True}

    def graph_context(self, symbol: str) -> GraphContext:
        name = symbol.split(".")[-1]
        definitions: list[dict] = []
        callers: list[dict] = []
        def_re = re.compile(rf"^\s*(?:async\s+def|def|class)\s+{re.escape(name)}\b")
        call_re = re.compile(rf"\b{re.escape(name)}\s*\(")
        for path in self._files():
            rel = str(path.relative_to(self.repo))
            for lineno, line in enumerate(self._read(path), 1):
                if def_re.search(line):
                    definitions.append({"name": name, "qualname": name, "kind": "unknown", "file": rel, "line": lineno, "end_line": lineno})
                    continue
                if call_re.search(line):
                    callers.append({"file": rel, "caller": "<grep>", "line": lineno})
        return GraphContext(
            symbol=symbol,
            definitions=definitions,
            callers=callers,
            callees=[],
            blast_radius=[],
            degraded=True,
            backend=self.backend,
        )

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        if shutil.which("rg"):
            return self._rg_search(query, k)
        return self._python_search(query, k)

    def _rg_search(self, query: str, k: int) -> list[SearchHit]:
        proc = subprocess.run(
            ["rg", "--json", query, str(self.repo)],
            text=True,
            capture_output=True,
            timeout=10,
        )
        hits: list[SearchHit] = []
        for raw in proc.stdout.splitlines():
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event["data"]
            path = Path(data["path"]["text"])
            rel = str(path.relative_to(self.repo)) if path.is_absolute() else str(path)
            hits.append(
                SearchHit(
                    file=rel,
                    line=int(data.get("line_number", 1)),
                    score=1.0,
                    snippet=data.get("lines", {}).get("text", "").rstrip(),
                    backend=self.backend,
                )
            )
            if len(hits) >= k:
                break
        return hits

    def _python_search(self, query: str, k: int) -> list[SearchHit]:
        needle = query.lower()
        hits: list[SearchHit] = []
        for path in self._files():
            rel = str(path.relative_to(self.repo))
            for lineno, line in enumerate(self._read(path), 1):
                if needle in line.lower():
                    hits.append(SearchHit(rel, lineno, 1.0, line.rstrip(), self.backend))
                    if len(hits) >= k:
                        return hits
        return hits

    def _files(self) -> list[Path]:
        skip = {".git", ".venv", "venv", "__pycache__", ".axon"}
        out = []
        for path in sorted(self.repo.rglob("*.py")):
            if any(part in skip for part in path.relative_to(self.repo).parts[:-1]):
                continue
            out.append(path)
        return out

    @staticmethod
    def _read(path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
