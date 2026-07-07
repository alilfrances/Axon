"""Central per-repo data store (~/.axon/data/<repo-path-hash>/).

Mirrors Cortex's layout: repo state (index db, sandbox venv) lives outside
the target repo. Repos with an existing in-repo .axon/ keep using it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

LEGACY_DIR_NAME = ".axon"


def data_root() -> Path:
    """Base directory for all central per-repo data dirs."""
    override = os.environ.get("AXON_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".axon" / "data"


def repo_data_dir(repo_path: Path) -> Path:
    """Central data dir for one repo, keyed by hash of its resolved path."""
    resolved = Path(repo_path).resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return data_root() / digest


def default_db_path(repo_path: Path) -> Path:
    root = Path(repo_path).resolve()
    legacy = root / LEGACY_DIR_NAME / "index.db"
    if legacy.exists():
        return legacy
    return repo_data_dir(root) / "index.db"


def default_venv_dir(repo_path: Path) -> Path:
    root = Path(repo_path).resolve()
    legacy = root / LEGACY_DIR_NAME / "venv"
    if legacy.exists():
        return legacy
    return repo_data_dir(root) / "venv"


def gc_data_dirs(prune: bool = False) -> dict:
    """Classify central data dirs by whether their source repo still exists."""
    result: dict[str, list[dict[str, str | None]]] = {
        "active": [],
        "orphaned": [],
        "unknown": [],
        "pruned": [],
    }
    base = data_root()
    if not base.is_dir():
        return result
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            result["unknown"].append({"dir": str(entry), "repo_path": None})
            continue
        try:
            repo_path = json.loads(meta_path.read_text(encoding="utf-8")).get("repo_path")
        except (json.JSONDecodeError, OSError):
            result["unknown"].append({"dir": str(entry), "repo_path": None})
            continue
        record = {"dir": str(entry), "repo_path": repo_path}
        if repo_path and Path(repo_path).is_dir():
            result["active"].append(record)
        else:
            result["orphaned"].append(record)
            if prune:
                shutil.rmtree(entry)
                result["pruned"].append(record)
    return result


def write_repo_meta(data_path: Path, repo_root: Path) -> None:
    """Record which repo a central data dir belongs to, for gc and debugging."""
    parent = data_path.parent
    if parent.name == LEGACY_DIR_NAME:
        return
    parent.mkdir(parents=True, exist_ok=True)
    meta = {"repo_path": str(Path(repo_root).resolve()), "updated_at": int(time.time())}
    (parent / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
