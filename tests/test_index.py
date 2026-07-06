from __future__ import annotations

from axon.index import RepoIndex


def test_repo_index_incremental_symbol_callers_and_blast_radius(fixture_repo):
    repo = fixture_repo()
    index = RepoIndex(repo)
    try:
        stats = index.refresh()
        assert stats["parsed"] == 4
        assert index.refresh()["parsed"] == 0

        core = repo / "calc" / "core.py"
        core.write_text(core.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert index.refresh()["parsed"] == 1

        (repo / "calc" / "api.py").unlink()
        stats = index.refresh()
        assert stats["removed"] == 1

        divide = index.find_symbol("divide")
        assert divide and divide[0].file == "calc/core.py"
        assert any(c["caller"] == "use_divide" for c in index.callers_of("divide"))
        assert "calc/core.py" in index.blast_radius("divide")
    finally:
        index.close()
