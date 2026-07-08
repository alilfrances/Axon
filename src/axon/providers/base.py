"""Context provider contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SearchHit:
    file: str
    line: int
    score: float
    snippet: str
    backend: str


@dataclass(frozen=True)
class GraphContext:
    symbol: str
    definitions: list[dict] = field(default_factory=list)
    callers: list[dict] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    blast_radius: list[str] = field(default_factory=list)
    degraded: bool = False
    backend: str = ""
    # Human-readable scope/degradation note, e.g. when a symbol isn't found or
    # analysis is limited to one language. Empty when there's nothing to flag.
    note: str = ""


def dedupe_hits(hits: list["SearchHit"], k: int) -> list["SearchHit"]:
    """Collapse repeated file+snippet rows (chunk overlap yields the same span
    at several ranks) while preserving order, returning at most ``k`` hits."""
    out: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.file, hit.snippet)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= k:
            break
    return out


class ContextProvider(Protocol):
    backend: str

    def index(self, repo: Path) -> dict:
        pass

    def graph_context(self, symbol: str) -> GraphContext:
        pass

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        pass
