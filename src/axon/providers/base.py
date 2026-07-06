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


class ContextProvider(Protocol):
    backend: str

    def index(self, repo: Path) -> dict: ...

    def graph_context(self, symbol: str) -> GraphContext: ...

    def search(self, query: str, k: int = 10) -> list[SearchHit]: ...
