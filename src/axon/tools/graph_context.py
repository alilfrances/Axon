"""Tool wrapper for graph context lookup."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from axon.providers.select import select_provider


def get_graph_context(repo: Path, symbol: str) -> dict:
    provider = select_provider(repo)
    return asdict(provider.graph_context(symbol))
