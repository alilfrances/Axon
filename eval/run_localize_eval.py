"""Deterministic File@3 localization eval on real SWE-bench Verified repos.

No LLM, no Docker. For each instance: shallow-fetch the repo at base_commit,
index it with Axon's BuiltinProvider, run `localize` on the problem statement,
and check whether any gold-patch file appears in the top-k suspects.

This measures Target A (localization) — the one headline metric reachable
without an agent budget or the SWE-bench Docker harness.

Usage:
  python eval/run_localize_eval.py --repos psf/requests pallets/flask --max 12 --k 3
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from axon.index import RepoIndex  # noqa: E402
from axon.providers.builtin import BuiltinProvider  # noqa: E402
from axon.tools.localize import localize  # noqa: E402

_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/\S+", re.MULTILINE)


def gold_files(patch: str) -> set[str]:
    return set(_DIFF_FILE.findall(patch))


def shallow_fetch(repo: str, sha: str, dest: Path) -> bool:
    url = f"https://github.com/{repo}.git"
    try:
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dest, check=True)
        subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", sha],
                       cwd=dest, check=True, timeout=180)
        subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"    fetch failed: {exc}")
        return False


def eval_instance(inst: dict, k: int) -> bool | None:
    gold = gold_files(inst["patch"])
    gold_py = {f for f in gold if f.endswith(".py")}
    if not gold_py:
        return None  # non-Python target; out of v0 scope
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp)
        if not shallow_fetch(inst["repo"], inst["base_commit"], repo_dir):
            return None
        provider = BuiltinProvider(repo_dir)
        provider.index(repo_dir)
        index = RepoIndex(repo_dir)
        index.refresh()
        result = localize(provider, index, inst["problem_statement"], k=k)
        suspects = {s["file"] for s in result["suspects"][:k]}
        return bool(gold_py & suspects)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", required=True,
                    help="allowlist of repos to include (keep them small)")
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()

    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    rows = [r for r in ds if r["repo"] in set(args.repos)]
    rows.sort(key=lambda r: r["instance_id"])  # deterministic
    rows = rows[: args.max]

    hits = misses = skipped = 0
    print(f"Running File@{args.k} on {len(rows)} instances from {args.repos}\n")
    for r in rows:
        outcome = eval_instance(r, args.k)
        if outcome is None:
            skipped += 1
            tag = "SKIP"
        elif outcome:
            hits += 1
            tag = "HIT "
        else:
            misses += 1
            tag = "MISS"
        print(f"  [{tag}] {r['instance_id']}")

    scored = hits + misses
    rate = (hits / scored * 100) if scored else 0.0
    print(f"\nFile@{args.k}: {hits}/{scored} = {rate:.0f}%  (skipped {skipped})")
    print("NOTE: partial slice on lightweight repos — NOT the full frozen 60.")


if __name__ == "__main__":
    main()
