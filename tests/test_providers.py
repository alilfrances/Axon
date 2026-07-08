from __future__ import annotations

import subprocess
from types import SimpleNamespace

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


def test_select_provider_prefer_builtin(fixture_repo, capsys):
    repo = fixture_repo()
    provider = select_provider(repo, prefer="builtin")
    try:
        assert isinstance(provider, BuiltinProvider)
    finally:
        provider.close()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Axon provider: builtin" in captured.err


def test_select_provider_default_never_raises(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: False))
    provider = select_provider(repo)
    try:
        assert isinstance(provider, BuiltinProvider)
    finally:
        provider.close()


def test_cortex_index_success_refreshes_builtin_fallback(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: True))

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["cortex", "ingest"]:
            return SimpleNamespace(returncode=0, stdout='{"backend": "cortex", "indexed": true}')
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("axon.providers.cortex.subprocess.run", fake_run)
    provider = CortexProvider(repo)
    (repo / "calc" / "fresh.py").write_text(
        "def fresh_symbol():\n    return 'fresh'\n",
        encoding="utf-8",
    )

    stats = provider.index(repo)

    assert stats == {"backend": "cortex", "indexed": True}
    assert provider._using_fallback is False
    assert any(hit.file == "calc/fresh.py" for hit in provider._fallback.search("fresh_symbol", 5))


def test_cortex_index_failure_returns_refreshed_builtin_stats(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: True))

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["cortex", "ingest"]:
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("axon.providers.cortex.subprocess.run", fake_run)
    provider = CortexProvider(repo)
    (repo / "calc" / "failed.py").write_text(
        "def failed_symbol():\n    return 'failed'\n",
        encoding="utf-8",
    )

    stats = provider.index(repo)

    assert stats["backend"] == "cortex-fallback-builtin"
    assert stats["files"] >= 4
    assert provider._using_fallback is True
    assert any(hit.file == "calc/failed.py" for hit in provider.search("failed_symbol", 5))


def test_cortex_index_timeout_surfaces_reason(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: True))

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["cortex", "ingest"]:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("axon.providers.cortex.subprocess.run", fake_run)
    provider = CortexProvider(repo)

    stats = provider.index(repo)

    assert stats["backend"] == "cortex-fallback-builtin"
    assert "timed out" in stats["fallback_reason"]
    assert "AXON_CORTEX_INGEST_TIMEOUT" in stats["fallback_reason"]


def test_cortex_ingest_timeout_is_configurable(monkeypatch, fixture_repo):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: True))
    monkeypatch.setenv("AXON_CORTEX_INGEST_TIMEOUT", "900")
    seen: dict[str, int] = {}

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["cortex", "ingest"]:
            seen["timeout"] = kwargs.get("timeout")
            return SimpleNamespace(returncode=0, stdout='{"backend": "cortex"}')
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("axon.providers.cortex.subprocess.run", fake_run)
    CortexProvider(repo).index(repo)

    assert seen["timeout"] == 900


def test_cortex_ingest_timeout_default_and_progress(monkeypatch, fixture_repo, capsys):
    repo = fixture_repo()
    monkeypatch.setattr(CortexProvider, "available", classmethod(lambda cls: True))
    seen: dict[str, int] = {}

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["cortex", "ingest"]:
            seen["timeout"] = kwargs.get("timeout")
            return SimpleNamespace(returncode=0, stdout='{"backend": "cortex"}')
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("axon.providers.cortex.subprocess.run", fake_run)
    provider = CortexProvider(repo)
    try:
        provider.index(repo)
    finally:
        provider.close()

    assert seen["timeout"] == 600
    assert "cortex ingest in progress" in capsys.readouterr().err


def test_builtin_search_dedupes_repeated_rows(fixture_repo):
    repo = fixture_repo()
    provider = BuiltinProvider(repo)
    try:
        hits = provider.search("divide", 10)
        keys = [(hit.file, hit.snippet) for hit in hits]
        assert len(keys) == len(set(keys))
    finally:
        provider.close()


def test_builtin_fallback_searches_text_extensions(tmp_path):
    repo = tmp_path / "mixed"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "math.cpp").write_text(
        "int divide_zero_guard(int value) {\n    return value == 0 ? 0 : 42 / value;\n}\n",
        encoding="utf-8",
    )
    provider = BuiltinProvider(repo)
    try:
        stats = provider.index(repo)
        hits = provider.search("divide_zero_guard", 5)
    finally:
        provider.close()

    assert stats["python_files"] == 0
    assert stats["text_files"] == 1
    assert "full-text search across 1 files" in stats["note"]
    assert hits and hits[0].file == "src/math.cpp"


def test_grep_provider_counts_text_extensions(tmp_path):
    repo = tmp_path / "mixed"
    repo.mkdir()
    (repo / "Widget.swift").write_text("func renderWidget() {}\n", encoding="utf-8")

    stats = GrepProvider(repo).index(repo)

    assert stats["files"] == 1
    assert stats["python_files"] == 0
    assert stats["text_files"] == 1


def test_builtin_graph_context_notes_missing_symbol(fixture_repo):
    repo = fixture_repo()
    provider = BuiltinProvider(repo)
    try:
        ctx = provider.graph_context("NoSuchSymbolAnywhere")
        assert ctx.definitions == []
        assert "Python-only" in ctx.note
        assert "indexed" in ctx.note
    finally:
        provider.close()
