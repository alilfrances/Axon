from __future__ import annotations

import json
from pathlib import Path

from axon.store import (
    data_root,
    default_db_path,
    default_venv_dir,
    gc_data_dirs,
    repo_data_dir,
    write_repo_meta,
)


def test_data_root_honors_override(tmp_path, monkeypatch):
    monkeypatch.setenv("AXON_DATA_DIR", str(tmp_path / "custom"))
    assert data_root() == (tmp_path / "custom").resolve()


def test_repo_data_dir_stable_and_distinct(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert repo_data_dir(a) == repo_data_dir(a)
    assert repo_data_dir(a) != repo_data_dir(b)
    assert repo_data_dir(a).parent == data_root()


def test_default_paths_central_when_no_legacy(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert default_db_path(repo) == repo_data_dir(repo) / "index.db"
    assert default_venv_dir(repo) == repo_data_dir(repo) / "venv"


def test_default_paths_prefer_legacy(tmp_path):
    repo = tmp_path / "repo"
    legacy = repo / ".axon"
    legacy.mkdir(parents=True)
    (legacy / "index.db").touch()
    (legacy / "venv").mkdir()
    assert default_db_path(repo) == (legacy / "index.db").resolve()
    assert default_venv_dir(repo) == (legacy / "venv").resolve()


def test_write_repo_meta(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db = default_db_path(repo)
    write_repo_meta(db, repo)
    meta = json.loads((db.parent / "meta.json").read_text(encoding="utf-8"))
    assert meta["repo_path"] == str(repo.resolve())


def test_write_repo_meta_skips_legacy_dir(tmp_path):
    repo = tmp_path / "repo"
    legacy = repo / ".axon"
    legacy.mkdir(parents=True)
    write_repo_meta(legacy / "index.db", repo)
    assert not (legacy / "meta.json").exists()


def _make_data_dir(repo_path: str) -> Path:
    entry = data_root() / f"dir_{abs(hash(repo_path)) % 10**8:08d}"
    entry.mkdir(parents=True)
    (entry / "meta.json").write_text(
        json.dumps({"repo_path": repo_path, "updated_at": 0}), encoding="utf-8"
    )
    return entry


def test_gc_classifies_and_prunes(tmp_path):
    live_repo = tmp_path / "live"
    live_repo.mkdir()
    live = _make_data_dir(str(live_repo))
    orphan = _make_data_dir(str(tmp_path / "gone"))
    unknown = data_root() / "no_meta"
    unknown.mkdir(parents=True)

    listed = gc_data_dirs(prune=False)
    assert [r["dir"] for r in listed["active"]] == [str(live)]
    assert [r["dir"] for r in listed["orphaned"]] == [str(orphan)]
    assert [r["dir"] for r in listed["unknown"]] == [str(unknown)]
    assert listed["pruned"] == []
    assert orphan.exists()

    pruned = gc_data_dirs(prune=True)
    assert [r["dir"] for r in pruned["pruned"]] == [str(orphan)]
    assert not orphan.exists()
    assert live.exists()
    assert unknown.exists()


def test_gc_empty_when_no_data_root():
    result = gc_data_dirs()
    assert result == {"active": [], "orphaned": [], "unknown": [], "pruned": []}
