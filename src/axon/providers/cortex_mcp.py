"""Minimal stdio client for the Cortex MCP server.

Speaks the newline-delimited JSON-RPC protocol served by `cortex mcp`
(cortex.mcp.server): initialize -> notifications/initialized -> tools/list ->
tools/call. Written against Cortex's actual server source rather than the MCP
SDK -- the surface is three methods and the server is synchronous, so a small
synchronous client avoids pulling async plumbing into the provider layer.

Unlike the CLI adapter's per-call `cortex ingest`, the MCP tools run against
Cortex's persistent per-repo database and auto-refresh it incrementally when
stale, so large repos pay the full ingest cost at most once.
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import time
from pathlib import Path

_PROTOCOL_VERSION = "2024-11-05"
_START_TIMEOUT_S = 15
# Tools the adapter actually calls; a server missing any of them is unusable.
_REQUIRED_TOOLS = {"cortex_query", "cortex_search_symbols", "cortex_references", "cortex_refresh"}


class CortexMcpError(RuntimeError):
    """Transport-level failure: launch, handshake, timeout, or server exit."""


class CortexMcpToolError(CortexMcpError):
    """A tools/call returned isError=true; `payload` holds the server's error
    object (e.g. {"error": "missing_db", ...}) so callers can react to it."""

    def __init__(self, payload: dict):
        self.payload = payload if isinstance(payload, dict) else {}
        super().__init__(self.payload.get("message") or self.payload.get("error") or "tool error")


def mcp_command() -> list[str]:
    raw = os.environ.get("AXON_CORTEX_MCP_CMD") or "cortex mcp"
    return shlex.split(raw)


class CortexMcpClient:
    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()
        self._cmd = mcp_command()
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._next_id = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=str(self.repo),
            )
        except OSError as exc:
            raise CortexMcpError(f"cannot launch {' '.join(self._cmd)!r}: {exc}") from exc
        threading.Thread(target=self._pump, daemon=True).start()
        self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "axon", "version": "0"},
            },
            _START_TIMEOUT_S,
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listing = self._request("tools/list", {}, _START_TIMEOUT_S)
        names = {tool.get("name") for tool in listing.get("tools", []) if isinstance(tool, dict)}
        missing = _REQUIRED_TOOLS - names
        if missing:
            raise CortexMcpError(f"server lacks expected tools: {sorted(missing)}")

    def call_tool(self, name: str, arguments: dict, timeout_s: float) -> dict:
        """Call one tool and return its decoded JSON payload."""
        result = self._request("tools/call", {"name": name, "arguments": arguments}, timeout_s)
        content = result.get("content") or []
        text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"error": "bad_payload", "message": text[:200]}
        if not isinstance(payload, dict):
            payload = {"error": "bad_payload", "message": "non-object tool payload"}
        if result.get("isError"):
            raise CortexMcpToolError(payload)
        return payload

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # -- transport -------------------------------------------------------------

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            self._lines.put(None)
            return
        try:
            for line in proc.stdout:
                self._lines.put(line)
        except ValueError:
            pass  # stdout closed during shutdown
        finally:
            self._lines.put(None)

    def _send(self, frame: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise CortexMcpError("cortex MCP server is not running")
        try:
            proc.stdin.write(json.dumps(frame) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise CortexMcpError(f"cortex MCP server pipe closed: {exc}") from exc

    def _request(self, method: str, params: dict, timeout_s: float) -> dict:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise CortexMcpError(f"{method} timed out after {timeout_s}s")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    self.close()
                    raise CortexMcpError(f"{method} timed out after {timeout_s}s") from None
                if line is None:
                    raise CortexMcpError("cortex MCP server exited")
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(frame, dict) or frame.get("id") != request_id:
                    continue
                if "error" in frame:
                    raise CortexMcpError(str(frame["error"].get("message", "rpc error")))
                result = frame.get("result")
                return result if isinstance(result, dict) else {}
