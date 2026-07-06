from __future__ import annotations

from axon.providers.builtin import BuiltinProvider
from axon.providers.cortex import CortexProvider
from axon.providers.grep import GrepProvider
from axon.providers.select import select_provider


def test_builtin_provider_graph_and_search(fixture_repo):
    repo = fixture_repo()
    provider = BuiltinProvider(repo)
    try:
        ctx = provider.graph_context("divide")
        assert any(d["file"] == "calc/core.py" for d in ctx.definitions)
        assert any(c["file"] == "calc/api.py" for c in ctx.callers)
        assert "calc/api.py" in ctx.blast_radius
        assert ctx.degraded is False

        hits = provider.search("divide zero", 3)
        assert any(hit.file == "calc/core.py" for hit in hits)
    finally:
        provider.close()


def test_grep_provider_degraded(fixture_repo):
    repo = fixture_repo()
    ctx = GrepProvider(repo).graph_context("divide")

    assert ctx.degraded is True
    assert ctx.blast_radius == []


def test_select_provider_prefer_builtin(fixture_repo):
    repo = fixture_repo()
    provider = select_provider(repo, prefer="builtin")
    try:
        assert isinstance(provider, BuiltinProvider)
    finally:
        provider.close()


def test_select_provider_default_never_raises(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: False))
    provider = select_provider(repo)
    try:
        assert isinstance(provider, BuiltinProvider)
    finally:
        provider.close()
