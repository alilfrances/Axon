"""Provider selection ladder."""

from __future__ import annotations

from pathlib import Path
import sys

from .base import ContextProvider
from .builtin import BuiltinProvider
from .cortex import CortexProvider
from .grep import GrepProvider


def select_provider(repo: Path, prefer: str | None = None) -> ContextProvider:
    repo = Path(repo).resolve()
    provider: ContextProvider
    if prefer == "builtin":
        provider = BuiltinProvider(repo)
    elif prefer == "grep":
        provider = GrepProvider(repo)
    elif prefer == "cortex":
        provider = CortexProvider(repo)
    else:
        try:
            provider = CortexProvider(repo) if CortexProvider.available() else BuiltinProvider(repo)
        except Exception:
            provider = GrepProvider(repo)
    print(f"Axon provider: {provider.backend}", file=sys.stderr, flush=True)
    return provider
