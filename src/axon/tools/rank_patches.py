"""Batch verify and rank candidate patches."""

from __future__ import annotations

from pathlib import Path

from axon.tools.verify_fix import (
    _apply_patch,
    _failure_ids,
    _is_git_repo,
    _passed,
    _revert_patch,
    _run_pytest,
)

_VERDICT_ORDER = {"pass": 0, "regressions": 1, "fix-does-not-fix": 2, "apply-failed": 3}


def rank_patches(
    repo: str,
    patches: list[str],
    repro_test: str,
    timeout: int = 600,
    max_patches: int = 8,
) -> dict:
    root = Path(repo).resolve()
    patches = patches[:max_patches]
    repro_before = _run_pytest(root, repro_test, timeout)
    if _passed(repro_before):
        return {"ranked": [], "best_index": None, "repro_before": repro_before, "note": "repro-not-red"}

    baseline = _run_pytest(root, None, timeout)
    baseline_failures = _failure_ids(baseline)
    method = "git" if _is_git_repo(root) else "fallback"

    normalized_seen: dict[str, int] = {}
    entries: list[dict] = []
    for idx, patch in enumerate(patches):
        norm = _normalize(patch)
        if norm in normalized_seen:
            entries.append(
                {
                    "patch_index": idx,
                    "verdict": "duplicate",
                    "regressions": [],
                    "changed_lines": _changed_lines(patch),
                    "duplicate_of": normalized_seen[norm],
                }
            )
            continue
        normalized_seen[norm] = idx
        entries.append(_verify_one(root, patch, idx, repro_test, timeout, method, baseline_failures))

    unique = [entry for entry in entries if entry["verdict"] != "duplicate"]
    unique.sort(
        key=lambda entry: (
            _VERDICT_ORDER[entry["verdict"]],
            len(entry["regressions"]),
            entry["changed_lines"],
            entry["patch_index"],
        )
    )
    dupes = [entry for entry in entries if entry["verdict"] == "duplicate"]
    ranked = unique + dupes
    best = ranked[0]["patch_index"] if ranked and ranked[0]["verdict"] == "pass" else None
    return {"ranked": ranked, "best_index": best, "repro_before": repro_before, "note": None}


def _verify_one(
    root: Path,
    patch: str,
    idx: int,
    repro_test: str,
    timeout: int,
    method: str,
    baseline_failures: set[str],
) -> dict:
    changed_lines = _changed_lines(patch)
    apply_result = _apply_patch(root, patch, method)
    if apply_result["exit_code"] != 0:
        return {
            "patch_index": idx,
            "verdict": "apply-failed",
            "regressions": [],
            "changed_lines": changed_lines,
            "duplicate_of": None,
        }
    try:
        repro_after = _run_pytest(root, repro_test, timeout)
        full_after = _run_pytest(root, None, timeout)
    finally:
        _revert_patch(root, patch, method, apply_result)
    regressions = sorted(_failure_ids(full_after) - baseline_failures)
    if not _passed(repro_after):
        verdict = "fix-does-not-fix"
    elif regressions:
        verdict = "regressions"
    else:
        verdict = "pass"
    return {
        "patch_index": idx,
        "verdict": verdict,
        "regressions": regressions,
        "changed_lines": changed_lines,
        "duplicate_of": None,
    }


def _normalize(patch: str) -> str:
    lines = [line.rstrip() for line in patch.splitlines() if not line.startswith("index ") and line.strip()]
    return "\n".join(lines)


def _changed_lines(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )
