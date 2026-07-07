"""Defensive Cortex CLI adapter.

Cortex's `query`/`index` subcommands were replaced by `ingest`, `bundle`,
and `graph export` (see cortex CHANGELOG). This adapter shells out to the
current CLI surface only -- no MCP client, no import of the `cortex`
package -- so it stays isolated if Cortex's CLI changes again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
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
                ["cortex", "ingest", str(self.repo)],
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
                ctx = self._graph_context_via_export(symbol)
                if ctx is not None:
                    return ctx
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

    def _graph_context_via_export(self, symbol: str) -> GraphContext | None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "graph.json"
            proc = subprocess.run(
                ["cortex", "graph", "export", str(self.repo), "--format", "json", "--out", str(out_path)],
                text=True,
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0 or not out_path.exists():
                return None
            data = json.loads(out_path.read_text())

        nodes = {n["node_id"]: n for n in data.get("nodes", [])}
        matches = [n for n in nodes.values() if n.get("label") == symbol]
        if not matches:
            return None
        matches.sort(key=lambda n: n.get("granularity") != "symbol")

        definitions = [
            {"file": n["source_ref"], "line": n.get("span_start") or n.get("metadata", {}).get("lineno", 1)}
            for n in matches
        ]
        target_ids = {n["node_id"] for n in matches}

        callers, callees, blast_radius = [], [], set()
        for edge in data.get("edges", []):
            if edge["target"] in target_ids:
                caller = nodes.get(edge["source"])
                if caller:
                    callers.append(caller.get("label", edge["source"]))
                    blast_radius.add(caller.get("source_ref", edge["source"]))
            if edge["source"] in target_ids:
                callee = nodes.get(edge["target"])
                if callee:
                    callees.append(callee.get("label", edge["target"]))
                    blast_radius.add(callee.get("source_ref", edge["target"]))

        return GraphContext(
            symbol=symbol,
            definitions=definitions,
            callers=callers,
            callees=callees,
            blast_radius=sorted(blast_radius),
            degraded=False,
            backend=self.backend,
        )

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        if not self._using_fallback:
            try:
                proc = subprocess.run(
                    ["cortex", "bundle", str(self.repo), "--task", query, "--format", "json", "--budget", "4000"],
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    return [
                        SearchHit(
                            file=item.get("path", item.get("title", "")),
                            line=item.get("metadata", {}).get("lineno", 1),
                            score=float(item.get("score", 0.0)),
                            snippet=item.get("content", "")[:200],
                            backend=self.backend,
                        )
                        for item in data.get("items", [])[:k]
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
