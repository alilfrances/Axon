"""Defensive Cortex CLI adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .base import GraphContext, SearchHit
from .builtin import BuiltinProvider


class CortexProvider:
    backend = "cortex"

    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()
        self._fallback = BuiltinProvider(self.repo)
        self._using_fallback = not self.available()

    @classmethod
    def available(cls) -> bool:
        exe = shutil.which("cortex")
        if not exe:
            return False
        try:
            proc = subprocess.run([exe, "--help"], capture_output=True, timeout=5)
        except Exception:
            return False
        return proc.returncode == 0

    def index(self, repo: Path) -> dict:
        self.repo = Path(repo).resolve()
        try:
            proc = subprocess.run(
                ["cortex", "index", str(self.repo)],
                text=True,
                capture_output=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return self._json_or_status(proc.stdout, {"backend": self.backend, "indexed": True})
        except Exception:
            pass
        out = self._fallback.index(self.repo)
        out["backend"] = "cortex-fallback-builtin"
        self._using_fallback = True
        return out

    def graph_context(self, symbol: str) -> GraphContext:
        if not self._using_fallback:
            try:
                proc = subprocess.run(
                    ["cortex", "query", "graph_context", symbol, "--repo", str(self.repo), "--json"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    return GraphContext(backend=self.backend, degraded=False, **data)
            except Exception:
                self._using_fallback = True
        ctx = self._fallback.graph_context(symbol)
        return GraphContext(
            symbol=ctx.symbol,
            definitions=ctx.definitions,
            callers=ctx.callers,
            callees=ctx.callees,
            blast_radius=ctx.blast_radius,
            degraded=ctx.degraded,
            backend="cortex-fallback-builtin",
        )

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        if not self._using_fallback:
            try:
                proc = subprocess.run(
                    ["cortex", "query", "search", query, "--repo", str(self.repo), "--json"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    return [
                        SearchHit(
                            file=item["file"],
                            line=int(item.get("line", 1)),
                            score=float(item.get("score", 0.0)),
                            snippet=item.get("snippet", ""),
                            backend=self.backend,
                        )
                        for item in data[:k]
                    ]
            except Exception:
                self._using_fallback = True
        return [
            SearchHit(hit.file, hit.line, hit.score, hit.snippet, "cortex-fallback-builtin")
            for hit in self._fallback.search(query, k)
        ]

    @staticmethod
    def _json_or_status(raw: str, fallback: dict) -> dict:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else fallback
        except json.JSONDecodeError:
            return fallback
