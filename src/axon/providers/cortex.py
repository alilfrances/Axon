"""Defensive Cortex adapter: MCP first, CLI second, builtin last.

Preferred transport is the Cortex MCP server (`cortex mcp`, override via
AXON_CORTEX_MCP_CMD): its tools run against Cortex's persistent per-repo
database with incremental auto-refresh, so a large repo pays the full ingest
cost at most once instead of per call. When the MCP server can't be reached
the adapter falls back to shelling out to the `ingest`/`bundle`/`graph
export` CLI, and below that to the builtin BM25 backend -- recording *why*
it degraded at each step. No import of the `cortex` package either way, so
the adapter stays isolated if Cortex's interfaces change again.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .base import GraphContext, SearchHit, dedupe_hits
from .builtin import BuiltinProvider
from .cortex_mcp import CortexMcpClient, CortexMcpError, CortexMcpToolError

# Default per-call budgets (seconds). Cortex's first `ingest` of a large repo
# can take minutes, so these are generous and overridable via the environment
# (AXON_CORTEX_INGEST_TIMEOUT / _BUNDLE_TIMEOUT / _GRAPH_TIMEOUT). Too-tight
# budgets were the root cause of silent builtin fallback on big repos.
_DEFAULT_TIMEOUTS = {"ingest": 120, "bundle": 30, "graph": 60}


def _timeout(kind: str) -> int:
    raw = os.environ.get(f"AXON_CORTEX_{kind.upper()}_TIMEOUT")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_TIMEOUTS[kind]


def _warn_fallback(reason: str | None) -> None:
    if reason:
        print(f"Axon: cortex unavailable, using builtin fallback ({reason})",
              file=sys.stderr, flush=True)


class CortexProvider:
    backend = "cortex"
    mcp_backend = "cortex-mcp"

    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()
        self._fallback = BuiltinProvider(self.repo)
        self._using_fallback = not self.available()
        self._fallback_reason: str | None = (
            "cortex CLI not found on PATH" if self._using_fallback else None
        )
        self._mcp: CortexMcpClient | None = None
        self._mcp_state = "untried"  # "untried" | "ready" | "failed"

    def close(self) -> None:
        self._drop_mcp(None)
        self._fallback.close()

    # -- MCP transport ---------------------------------------------------------

    def _mcp_client(self) -> CortexMcpClient | None:
        if self._mcp_state == "ready":
            return self._mcp
        if self._mcp_state == "failed":
            return None
        # Try MCP when a command is configured explicitly or cortex is on PATH;
        # otherwise skip straight to the CLI/builtin rungs without a subprocess.
        # AXON_CORTEX_MCP_CMD=off forces the CLI transport.
        raw_cmd = os.environ.get("AXON_CORTEX_MCP_CMD", "").strip()
        if raw_cmd.lower() in {"0", "off", "disabled"} or (
            not raw_cmd and shutil.which("cortex") is None
        ):
            self._mcp_state = "failed"
            return None
        client = CortexMcpClient(self.repo)
        try:
            client.start()
        except CortexMcpError as exc:
            client.close()
            self._mcp_state = "failed"
            print(f"Axon: cortex MCP unavailable, trying CLI ({exc})", file=sys.stderr, flush=True)
            return None
        self._mcp = client
        self._mcp_state = "ready"
        return client

    def _drop_mcp(self, reason: str | None) -> None:
        if self._mcp is not None:
            self._mcp.close()
            self._mcp = None
        self._mcp_state = "failed"
        if reason:
            print(f"Axon: cortex MCP failed, trying CLI ({reason})", file=sys.stderr, flush=True)

    def _mcp_call(self, client: CortexMcpClient, tool: str, arguments: dict, timeout_s: float) -> dict:
        """Call a tool; on Cortex's structured missing_db error, build the
        persistent index once via cortex_refresh and retry."""
        try:
            return client.call_tool(tool, arguments, timeout_s)
        except CortexMcpToolError as exc:
            if exc.payload.get("error") != "missing_db":
                raise
            client.call_tool("cortex_refresh", {"repo_path": str(self.repo)}, _timeout("ingest"))
            return client.call_tool(tool, arguments, timeout_s)

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
        fallback_stats = self._fallback.index(self.repo)
        client = self._mcp_client()
        if client is not None:
            try:
                payload = client.call_tool(
                    "cortex_refresh", {"repo_path": str(self.repo)}, _timeout("ingest")
                )
                return {
                    "backend": self.mcp_backend,
                    "indexed": True,
                    "summary": payload.get("summary") or {},
                }
            except CortexMcpError as exc:
                self._drop_mcp(f"cortex_refresh: {exc}")
        reason = self._fallback_reason
        if not self._using_fallback:
            reason = None
            budget = _timeout("ingest")
            try:
                proc = subprocess.run(
                    ["cortex", "ingest", str(self.repo)],
                    text=True,
                    capture_output=True,
                    timeout=budget,
                )
                if proc.returncode == 0:
                    return self._json_or_status(proc.stdout, {"backend": self.backend, "indexed": True})
                stderr = (getattr(proc, "stderr", "") or "").strip()
                reason = f"cortex ingest exited {proc.returncode}" + (f": {stderr[:200]}" if stderr else "")
            except subprocess.TimeoutExpired:
                reason = (
                    f"cortex ingest timed out after {budget}s "
                    "(raise AXON_CORTEX_INGEST_TIMEOUT for large repos)"
                )
            except Exception as exc:
                reason = f"cortex ingest failed: {type(exc).__name__}: {exc}"
        out = fallback_stats
        out["backend"] = "cortex-fallback-builtin"
        out["fallback_reason"] = reason
        self._using_fallback = True
        self._fallback_reason = reason
        _warn_fallback(reason)
        return out

    def graph_context(self, symbol: str) -> GraphContext:
        client = self._mcp_client()
        if client is not None:
            try:
                ctx = self._graph_context_via_mcp(client, symbol)
                if ctx is not None:
                    return ctx
            except CortexMcpError as exc:
                self._drop_mcp(f"graph context: {exc}")
        if not self._using_fallback:
            try:
                ctx = self._graph_context_via_export(symbol)
                if ctx is not None:
                    return ctx
            except Exception as exc:
                self._using_fallback = True
                self._fallback_reason = f"cortex graph export failed: {type(exc).__name__}"
                _warn_fallback(self._fallback_reason)
        ctx = self._fallback.graph_context(symbol)
        return GraphContext(
            symbol=ctx.symbol,
            definitions=ctx.definitions,
            callers=ctx.callers,
            callees=ctx.callees,
            blast_radius=ctx.blast_radius,
            degraded=ctx.degraded,
            backend="cortex-fallback-builtin",
            note=ctx.note,
        )

    def _graph_context_via_mcp(self, client: CortexMcpClient, symbol: str) -> GraphContext | None:
        """Definitions from cortex_search_symbols + callers/blast radius from
        cortex_references. Returns None when Cortex has no such symbol so the
        caller can consult the fallback (which annotates why it's empty)."""
        payload = self._mcp_call(
            client,
            "cortex_search_symbols",
            {"repo_path": str(self.repo), "query": symbol, "limit": 20},
            _timeout("graph"),
        )
        items = [n for n in payload.get("items", []) if isinstance(n, dict)]
        matches = [n for n in items if n.get("label") == symbol]
        if not matches:
            return None
        matches.sort(key=lambda n: n.get("granularity") != "symbol")
        definitions = [
            {
                "name": n.get("label", symbol),
                "qualname": n.get("label", symbol),
                "kind": n.get("kind", "unknown"),
                "file": n.get("source_ref", ""),
                "line": n.get("span_start") or 1,
                "end_line": n.get("span_end") or n.get("span_start") or 1,
            }
            for n in matches
        ]

        refs = self._mcp_call(
            client,
            "cortex_references",
            {"repo_path": str(self.repo), "symbol": symbol},
            _timeout("graph"),
        )
        buckets = refs.get("items") if isinstance(refs.get("items"), dict) else {}
        definition_sites = {(d["file"], d["line"]) for d in definitions}
        callers: list[dict] = []
        blast: set[str] = set()
        for ref in buckets.get("code", []):
            file, line = _split_ref(ref)
            if not file:
                continue
            blast.add(file)
            if (file, line) in definition_sites:
                continue
            callers.append({"file": file, "caller": "<cortex-ref>", "line": line})
        for bucket in ("script", "config", "doc", "other"):
            for ref in buckets.get(bucket, []):
                file, _ = _split_ref(ref)
                if file:
                    blast.add(file)

        return GraphContext(
            symbol=symbol,
            definitions=definitions,
            callers=callers,
            callees=[],
            blast_radius=sorted(blast),
            degraded=False,
            backend=self.mcp_backend,
            note="callees not reported by the cortex MCP backend",
        )

    def _graph_context_via_export(self, symbol: str) -> GraphContext | None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "graph.json"
            proc = subprocess.run(
                ["cortex", "graph", "export", str(self.repo), "--format", "json", "--out", str(out_path)],
                text=True,
                capture_output=True,
                timeout=_timeout("graph"),
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
        client = self._mcp_client()
        if client is not None:
            try:
                return self._search_via_mcp(client, query, k)
            except CortexMcpError as exc:
                self._drop_mcp(f"cortex_query: {exc}")
        if not self._using_fallback:
            try:
                proc = subprocess.run(
                    ["cortex", "bundle", str(self.repo), "--task", query, "--format", "json", "--budget", "4000"],
                    text=True,
                    capture_output=True,
                    timeout=_timeout("bundle"),
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    hits = [
                        SearchHit(
                            file=item.get("path", item.get("title", "")),
                            line=item.get("metadata", {}).get("lineno", 1),
                            score=float(item.get("score", 0.0)),
                            snippet=item.get("content", "")[:200],
                            backend=self.backend,
                        )
                        for item in data.get("items", [])
                    ]
                    return dedupe_hits(hits, k)
            except Exception as exc:
                self._using_fallback = True
                self._fallback_reason = f"cortex bundle failed: {type(exc).__name__}"
                _warn_fallback(self._fallback_reason)
        return [
            SearchHit(hit.file, hit.line, hit.score, hit.snippet, "cortex-fallback-builtin")
            for hit in self._fallback.search(query, k)
        ]

    def _search_via_mcp(self, client: CortexMcpClient, query: str, k: int) -> list[SearchHit]:
        payload = self._mcp_call(
            client,
            "cortex_query",
            {"repo_path": str(self.repo), "task": query, "budget": 4000},
            _timeout("bundle"),
        )
        hits = [
            SearchHit(
                file=item.get("path", ""),
                line=1,  # bundle items carry file-level spans, not line numbers
                score=float(item.get("score") or 0.0),
                snippet=(item.get("content") or "")[:200],
                backend=self.mcp_backend,
            )
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("path")
        ]
        return dedupe_hits(hits, k)

    @staticmethod
    def _json_or_status(raw: str, fallback: dict) -> dict:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else fallback
        except json.JSONDecodeError:
            return fallback


def _split_ref(ref: str) -> tuple[str, int]:
    """Parse cortex_references entries like "src/app.py:42" (line optional)."""
    if not isinstance(ref, str) or not ref:
        return "", 1
    path, sep, line = ref.rpartition(":")
    if sep and line.isdigit():
        return path, int(line)
    return ref, 1
