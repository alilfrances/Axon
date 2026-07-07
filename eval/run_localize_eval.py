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
_HUNK_DEF = re.compile(r"^@@[^@]*@@ .*?(?:async )?def (\w+)", re.MULTILINE)
_FILE_SPLIT = re.compile(r"^diff --git a/(\S+) b/\S+$", re.MULTILINE)


def gold_files(patch: str) -> set[str]:
    return set(_DIFF_FILE.findall(patch))


def gold_functions(patch: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    sections = _FILE_SPLIT.split(patch)
    for i in range(1, len(sections) - 1, 2):
        file, body = sections[i], sections[i + 1]
        if not file.endswith(".py"):
            continue
        for name in _HUNK_DEF.findall(body):
            out.add((file, name))
    return out


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


def eval_instance(inst: dict, ks: list[int]) -> dict[str, dict[int, bool]] | None:
    gold = gold_files(inst["patch"])
    gold_py = {f for f in gold if f.endswith(".py")}
    if not gold_py:
        return None  # non-Python target; out of v0 scope
    gold_fns = gold_functions(inst["patch"])
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp)
        if not shallow_fetch(inst["repo"], inst["base_commit"], repo_dir):
            return None
        provider = BuiltinProvider(repo_dir)
        try:
            provider.index(repo_dir)
            index = RepoIndex(repo_dir)
            try:
                index.refresh()
                result = localize(provider, index, inst["problem_statement"], k=max(ks))
            finally:
                index.close()
        finally:
            provider.close()
        suspects = result["suspects"]
        ranked = [s["file"] for s in suspects]
        file_hits = {k: bool(gold_py & set(ranked[:k])) for k in ks}
        function_hits = {
            k: bool(
                gold_fns
                and any(
                    (suspect["file"], fn["qualname"].split(".")[-1]) in gold_fns
                    for suspect in suspects[:k]
                    for fn in suspect.get("functions", [])
                )
            )
            for k in ks
        }
        return {"file": file_hits, "function": function_hits}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", required=True,
                    help="allowlist of repos to include (keep them small)")
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--k", type=int, nargs="+", default=[3])
    args = ap.parse_args()

    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    rows = [r for r in ds if r["repo"] in set(args.repos)]
    rows.sort(key=lambda r: r["instance_id"])  # deterministic
    rows = rows[: args.max]

    ks = sorted(set(args.k))
    file_hits = {k: 0 for k in ks}
    function_hits = {k: 0 for k in ks}
    scored = skipped = 0
    print(f"Running File@{ks} and Function@{ks} on {len(rows)} instances from {args.repos}\n")
    for r in rows:
        outcome = eval_instance(r, ks)
        if outcome is None:
            skipped += 1
            tag = "SKIP"
        else:
            scored += 1
            for k in ks:
                file_hits[k] += outcome["file"][k]
                function_hits[k] += outcome["function"][k]
            tag = " ".join(
                f"@{k}:F{'HIT' if outcome['file'][k] else 'MISS'}/"
                f"Fn{'HIT' if outcome['function'][k] else 'MISS'}"
                for k in ks
            )
        print(f"  [{tag}] {r['instance_id']}")

    for k in ks:
        file_rate = (file_hits[k] / scored * 100) if scored else 0.0
        fn_rate = (function_hits[k] / scored * 100) if scored else 0.0
        print(f"\nFile@{k}: {file_hits[k]}/{scored} = {file_rate:.0f}%  (skipped {skipped})")
        print(f"Function@{k}: {function_hits[k]}/{scored} = {fn_rate:.0f}%  (skipped {skipped})")
    print(f"NOTE: partial slice ({', '.join(args.repos)}, n={scored}) — NOT the frozen 60.")


if __name__ == "__main__":
    main()
