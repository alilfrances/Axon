# Axon v0.3 — Research-Grounded Debugging Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Axon's tools carry enough deterministic evidence (function-level suspects, runtime state at failure, guided workflow bundles, patch ranking) that a mid-tier agent debugs like a high-end one.

**Architecture:** Extend the existing deterministic-tools-behind-MCP design. No LLM calls inside Axon. Three new tools (`inspect`, `rank_patches`, `investigate`), plus upgrades to `localize` (git-recency signal, function-level suspects), `spectrum` (function aggregation, passing-test auto-selection, outcome-checked traces), and `repro` (failure classification + excerpt). Research grounding: Agentless/COSIL hierarchical file→function localization; LDB runtime-state verification (+9.8% debugging, small models need external ground truth); Otter execution-feedback repro loops; Agentless patch reranking via regression+repro tests; defect-prediction recency prior.

**Tech Stack:** Python ≥3.11 stdlib only (ast, sqlite3, subprocess, json). pytest via the repo's `.axon/venv` sandbox (existing `axon.sandbox`). No new runtime dependencies.

## Global Constraints

- Zero new runtime dependencies; stdlib + existing modules only.
- Every feature degrades gracefully: on any failure return `{"degraded": true, "note": ...}`-style results, never raise out of a tool entrypoint.
- All subprocess work goes through `axon.sandbox.run_in_sandbox` / `ensure_venv` (existing pattern in `run_tests.py`, `spectrum.py`).
- Untrusted input rule (see `refute.py`): any path from tool args must resolve inside the repo root (`Path.is_relative_to`) before reading.
- Tests: fast, in-memory/tmp_path fixtures from `tests/conftest.py` (`fixture_repo`, `git_fixture_repo`); no sleeps; deterministic.
- Reprs of user values are truncated (default 200 chars) before returning to the agent.
- Version bump 0.2.1 → 0.3.0 in `pyproject.toml`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (both spots in marketplace.json).
- Conventional commits (`feat:`, `test:`, `docs:`); one commit per task.

## File Structure

- Modify: `src/axon/tools/localize.py` — recency source, function-level suspects.
- Modify: `src/axon/tools/spectrum.py` — outcome-checked traces, passing auto-selection, function aggregation.
- Modify: `src/axon/_trace_runner.py` — emit exit code marker (already returns exit code; expose pass/fail in JSON).
- Create: `src/axon/_state_runner.py` — pytest plugin subprocess capturing exception frames + locals.
- Create: `src/axon/tools/inspect_run.py` — `inspect_test()` wrapper around the state runner.
- Modify: `src/axon/tools/repro.py` — failure classification + excerpt.
- Create: `src/axon/tools/rank_patches.py` — multi-patch verification + ranking.
- Create: `src/axon/tools/investigate.py` — composite evidence bundle + guided workflow.
- Modify: `src/axon/server.py` — register `inspect`, `rank_patches`, `investigate` (11 → 14 tools).
- Modify: `eval/run_localize_eval.py` — report Function@k alongside File@k.
- Modify: `README.md`, version files.
- Tests: `tests/test_localize.py`, `tests/test_spectrum.py`, `tests/test_repro.py`, plus new `tests/test_inspect.py`, `tests/test_rank_patches.py`, `tests/test_investigate.py`.

---

### Task 1: Git-recency signal in `localize`

Recently changed files are disproportionately likely to contain the bug (defect-prediction prior). Add a weak ranked-list source from `git log`.

**Files:**
- Modify: `src/axon/tools/localize.py`
- Test: `tests/test_localize.py`

**Interfaces:**
- Produces: `_recency_candidates(repo_root: str, limit: int = 20) -> list[dict]` (same candidate dict shape as other sources: `{"file", "line", "evidence"}`); `_WEIGHTS` gains `"recency": 0.5`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_localize.py`)

```python
def test_localize_recency_boosts_recently_changed_file(git_fixture_repo):
    from axon.index import RepoIndex
    from axon.providers.builtin import BuiltinProvider
    from axon.tools.localize import localize, _recency_candidates
    import subprocess

    root = git_fixture_repo()
    # Touch api.py in a second commit so it is the most recent change.
    (root / "calc" / "api.py").write_text(
        "from calc.core import divide\n\ndef ratio(a, b):\n    return divide(a, b)\n\ndef extra():\n    return 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "change api"], cwd=root, check=True, capture_output=True)

    cands = _recency_candidates(str(root))
    assert cands and cands[0]["file"] == "calc/api.py"
    assert "recent" in cands[0]["evidence"]

    provider = BuiltinProvider(root)
    provider.index(root)
    index = RepoIndex(root)
    index.refresh()
    result = localize(provider, index, "ratio computes wrong value in api")
    files = [s["file"] for s in result["suspects"]]
    assert "calc/api.py" in files


def test_recency_candidates_non_git_repo_empty(fixture_repo):
    from axon.tools.localize import _recency_candidates
    assert _recency_candidates(str(fixture_repo())) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_localize.py -k recency -v`
Expected: FAIL / ImportError (`_recency_candidates` not defined).

- [ ] **Step 3: Implement**

In `localize.py`: add `import subprocess` at top; add `"recency": 0.5` to `_WEIGHTS`; add the source to `ranked_lists` in `localize()` after the `"graph"` entry:

```python
        ("recency", _recency_candidates(str(index.repo_root))),
```

and the helper:

```python
def _recency_candidates(repo_root: str, limit: int = 20) -> list[dict]:
    try:
        proc = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", "-n", "50"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for name in proc.stdout.splitlines():
        name = name.strip()
        if not name.endswith(".py") or name in seen:
            continue
        seen.add(name)
        out.append({"file": name, "line": 1, "evidence": "recently changed (git log)"})
        if len(out) >= limit:
            break
    return out
```

- [ ] **Step 4: Run full localize tests**

Run: `python -m pytest tests/test_localize.py -v`
Expected: all PASS (existing fusion tests unaffected — weight 0.5 is the weakest source).

- [ ] **Step 5: Commit**

```bash
git add src/axon/tools/localize.py tests/test_localize.py
git commit -m "feat(localize): git-recency ranked-list source (defect-prediction prior)"
```

---

### Task 2: Function-level suspects in `localize`

File@k is measured; agents still need *which function*. Map every candidate line from every source to its enclosing function/method via the symbols table, aggregate weighted hits, attach top functions per suspect file. (Agentless/COSIL hierarchical localization.)

**Files:**
- Modify: `src/axon/tools/localize.py` (`_fuse` collects per-file line hits; new `_function_suspects`)
- Test: `tests/test_localize.py`

**Interfaces:**
- Consumes: `RepoIndex.conn` symbols table (`file`, `qualname`, `kind`, `line`, `end_line`).
- Produces: each suspect dict gains `"functions": [{"qualname": str, "line": int, "end_line": int, "score": float}]` (≤3, sorted by score desc). `_fuse(ranked_lists, k)` keeps its signature; `localize()` passes `index` into a post-fuse enrichment step: `_attach_functions(index, ranked_lists, suspects)`.

- [ ] **Step 1: Write the failing test**

```python
def test_localize_attaches_enclosing_functions(fixture_repo):
    from axon.index import RepoIndex
    from axon.providers.builtin import BuiltinProvider
    from axon.tools.localize import localize

    root = fixture_repo()
    provider = BuiltinProvider(root)
    provider.index(root)
    index = RepoIndex(root)
    index.refresh()
    bug = (
        "divide crashes\n"
        'Traceback (most recent call last):\n'
        '  File "calc/core.py", line 5, in divide\n'
        "ZeroDivisionError: division by zero\n"
    )
    result = localize(provider, index, bug)
    top = result["suspects"][0]
    assert top["file"] == "calc/core.py"
    quals = [f["qualname"] for f in top.get("functions", [])]
    assert "divide" in quals
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_localize.py::test_localize_attaches_enclosing_functions -v`
Expected: FAIL (`functions` missing).

- [ ] **Step 3: Implement**

In `localize()`, after `suspects = _fuse(ranked_lists, k)` add `_attach_functions(index, ranked_lists, suspects)`. Implementation:

```python
def _attach_functions(index: RepoIndex, ranked_lists: list[tuple[str, list[dict]]], suspects: list[dict]) -> None:
    suspect_files = {s["file"] for s in suspects}
    hits: dict[str, list[tuple[int, float]]] = {}
    for source, candidates in ranked_lists:
        weight = _WEIGHTS[source]
        for cand in candidates:
            file, line = cand.get("file"), int(cand.get("line", 1) or 1)
            if file in suspect_files and line > 1:
                hits.setdefault(file, []).append((line, weight))
    for suspect in suspects:
        scored: dict[str, dict] = {}
        for line, weight in hits.get(suspect["file"], []):
            row = index.conn.execute(
                "SELECT qualname, line, end_line FROM symbols"
                " WHERE file=? AND kind IN ('function','method') AND line<=? AND end_line>=?"
                " ORDER BY line DESC LIMIT 1",
                (suspect["file"], line, line),
            ).fetchone()
            if row is None:
                continue
            qualname, fn_line, fn_end = row
            entry = scored.setdefault(qualname, {"qualname": qualname, "line": fn_line, "end_line": fn_end, "score": 0.0})
            entry["score"] += weight
        functions = sorted(scored.values(), key=lambda f: (-f["score"], f["qualname"]))[:3]
        for fn in functions:
            fn["score"] = round(fn["score"], 3)
        suspect["functions"] = functions
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_localize.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/axon/tools/localize.py tests/test_localize.py
git commit -m "feat(localize): function-level suspects via symbol-range mapping"
```

---

### Task 3: Spectrum upgrade — outcome-checked traces, auto passing tests, function aggregation

Three fixes: (a) a "passing" test that actually fails currently pollutes Ochiai — check trace outcome; (b) when no passing tests are given, auto-collect siblings from the failing test's file (Ochiai needs `ep` to discriminate); (c) aggregate line scores to functions.

**Files:**
- Modify: `src/axon/_trace_runner.py` — JSON becomes `{"lines": {...}, "exit_code": int}` (keep printing on last stdout line).
- Modify: `src/axon/tools/spectrum.py`
- Test: `tests/test_spectrum.py`

**Interfaces:**
- Produces: `spectrum_localize(repo, failing_tests, passing_tests=None, top=20, auto_passing=True)`; result gains `"functions": [{"file","qualname","line","score"}]` (≤10) and `"passing_used": [test_ids]`. `_trace_test(repo, test_id) -> tuple[dict[tuple[str,int], bool], int]` (hits, exit_code).

- [ ] **Step 1: Write the failing tests**

```python
def test_trace_runner_reports_exit_code(fixture_repo):
    from axon.tools.spectrum import _trace_test
    root = fixture_repo()
    hits, code = _trace_test(root, "tests/test_calc.py::test_add")
    assert code == 0 and hits

def test_spectrum_auto_passing_and_functions(fixture_repo):
    from axon.tools.spectrum import spectrum_localize
    root = fixture_repo()
    result = spectrum_localize(str(root), ["tests/test_calc.py::test_divide_zero_returns_none"])
    assert not result["degraded"]
    assert "tests/test_calc.py::test_add" in result["passing_used"]
    quals = [f["qualname"] for f in result["functions"]]
    assert "divide" in quals
    # add() runs only in the passing test, so it must rank below divide().
    assert "add" not in quals[:1]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_spectrum.py -k "exit_code or auto_passing" -v`
Expected: FAIL (tuple unpack / missing keys).

- [ ] **Step 3: Implement**

`_trace_runner.py` `main()`: change final print to
`print(json.dumps({"lines": {...as before...}, "exit_code": int(exit_code)}))`.

`spectrum.py`:
- `_trace_test` parses the new shape (fallback: if parsed JSON has no `"lines"` key, treat whole dict as lines with exit_code from `result.exit_code`) and returns `(hits, exit_code)`.
- In `spectrum_localize`: failing traces keep hits regardless of code but note if a "failing" test passed; passing traces are kept **only** when `exit_code == 0`.
- Auto-passing when `auto_passing and not passing_tests`: take the file part of `failing_tests[0]` (`split("::")[0]`), run `[python, "-m", "pytest", "--collect-only", "-q", file]` via `run_in_sandbox` (timeout 30), parse node ids (lines containing `::`), drop ids in `failing_tests`, take first 3, trace each, keep those with exit code 0, record in `passing_used`.
- Function aggregation: build `RepoIndex(root)` + `refresh()`; for each scored `(file, line)` map to enclosing function with the same SQL as Task 2 (`kind IN ('function','method')`, innermost by `ORDER BY line DESC LIMIT 1`); per function keep `score = max(line scores)`; return top 10 sorted desc. Skip files not in the index (e.g. tests filtered by `_interesting` already).

- [ ] **Step 4: Run spectrum + localize tests** (localize consumes spectrum)

Run: `python -m pytest tests/test_spectrum.py tests/test_localize.py -v`
Expected: all PASS. Note `_spectrum_candidates` in `localize.py` calls `spectrum_localize(repo, [failing_test], top=k)` — signature stays compatible.

- [ ] **Step 5: Commit**

```bash
git add src/axon/_trace_runner.py src/axon/tools/spectrum.py tests/test_spectrum.py
git commit -m "feat(spectrum): outcome-checked traces, auto passing tests, function-level Ochiai"
```

---

### Task 4: `inspect` tool — runtime state at failure (LDB-style ground truth)

New tool: run a failing test, capture the exception chain with **per-frame locals** from live frames via a pytest plugin (`pytest_exception_interact`). This hands the agent the runtime facts a strong model would infer.

**Files:**
- Create: `src/axon/_state_runner.py`
- Create: `src/axon/tools/inspect_run.py`
- Modify: `src/axon/server.py`
- Test: `tests/test_inspect.py` (new)

**Interfaces:**
- Produces: `inspect_test(repo: str, test_target: str, timeout: int = 120) -> dict` returning
  `{"failures": [{"test_id": str, "exception_type": str, "message": str, "frames": [{"file": str, "line": int, "function": str, "locals": {name: repr_str}}]}], "degraded": bool, "note": str | None}`.
  Frames: repo-relative files only, max 15, innermost last; ≤20 locals/frame; reprs ≤200 chars; names starting with `__` skipped.
- MCP: `@app.tool(name="inspect") def inspect(repo: str, test_target: str, timeout: int = 120) -> dict`.

- [ ] **Step 1: Write the failing tests** (`tests/test_inspect.py`)

```python
from __future__ import annotations


def test_inspect_captures_exception_frames_and_locals(fixture_repo):
    from axon.tools.inspect_run import inspect_test
    root = fixture_repo()
    result = inspect_test(str(root), "tests/test_calc.py::test_divide_zero_returns_none")
    assert not result["degraded"]
    failure = result["failures"][0]
    assert failure["exception_type"] == "ZeroDivisionError"
    frames = failure["frames"]
    files = [f["file"] for f in frames]
    assert "calc/core.py" in files
    divide_frame = next(f for f in frames if f["function"] == "divide")
    assert divide_frame["locals"].get("b") == "0"


def test_inspect_passing_test_reports_no_failures(fixture_repo):
    from axon.tools.inspect_run import inspect_test
    root = fixture_repo()
    result = inspect_test(str(root), "tests/test_calc.py::test_add")
    assert result["failures"] == [] and not result["degraded"]


def test_inspect_bogus_target_degrades(fixture_repo):
    from axon.tools.inspect_run import inspect_test
    result = inspect_test(str(fixture_repo()), "tests/nope.py::test_missing")
    assert result["failures"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_inspect.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `_state_runner.py`**

```python
"""Run one pytest target; emit exception frames + locals as JSON (last stdout line)."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

_MAX_FRAMES = 15
_MAX_LOCALS = 20
_MAX_REPR = 200


def _safe_repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception as exc:  # repr() itself may raise on user objects
        text = f"<unreprable {type(value).__name__}: {type(exc).__name__}>"
    return text[:_MAX_REPR]


class _Collector:
    def __init__(self, repo: Path):
        self.repo = repo
        self.failures: list[dict] = []

    def pytest_exception_interact(self, node, call, report):
        excinfo = call.excinfo
        if excinfo is None:
            return
        frames: list[dict] = []
        tb = excinfo.tb  # py.code Traceback; iterate raw tb via _rawentry-free path
        raw = excinfo._excinfo[2]
        while raw is not None and len(frames) < _MAX_FRAMES * 2:
            frame = raw.tb_frame
            filename = Path(frame.f_code.co_filename)
            try:
                rel = str(filename.resolve().relative_to(self.repo))
            except ValueError:
                raw = raw.tb_next
                continue
            if any(part in {".venv", "venv", ".axon", ".git"} for part in Path(rel).parts):
                raw = raw.tb_next
                continue
            locals_out = {}
            for name, value in list(frame.f_locals.items())[:_MAX_LOCALS]:
                if name.startswith("__"):
                    continue
                locals_out[name] = _safe_repr(value)
            frames.append({
                "file": rel,
                "line": raw.tb_lineno,
                "function": frame.f_code.co_name,
                "locals": locals_out,
            })
            raw = raw.tb_next
        self.failures.append({
            "test_id": node.nodeid,
            "exception_type": excinfo.type.__name__,
            "message": _safe_repr(excinfo.value)[:_MAX_REPR],
            "frames": frames[-_MAX_FRAMES:],
        })


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print(json.dumps({"failures": [], "exit_code": 2}))
        return 2
    import pytest

    collector = _Collector(Path.cwd().resolve())
    with contextlib.redirect_stdout(sys.stderr):
        exit_code = pytest.main(["-q", "-p", "no:cacheprovider", argv[0]], plugins=[collector])
    print(json.dumps({"failures": collector.failures, "exit_code": int(exit_code)}))
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: `excinfo._excinfo[2]` is the raw traceback object (pytest's ExceptionInfo wraps `(type, value, tb)`). If pytest version in sandbox lacks it, fall back to `excinfo.value.__traceback__`. Use whichever exists: `raw = getattr(excinfo, "_excinfo", (None, None, excinfo.value.__traceback__))[2]`.

- [ ] **Step 4: Implement `tools/inspect_run.py`**

```python
"""Runtime-state inspection: exception frames + locals for a failing test."""

from __future__ import annotations

import json
from pathlib import Path

from axon.sandbox import ensure_venv, run_in_sandbox


def inspect_test(repo: str, test_target: str, timeout: int = 120) -> dict:
    root = Path(repo).resolve()
    python = ensure_venv(root, root / ".axon" / "venv")
    axon_src = Path(__file__).resolve().parents[2]
    result = run_in_sandbox(
        [str(python), "-m", "axon._state_runner", test_target],
        root,
        timeout,
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{root}:{axon_src}"},
    )
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"failures": [], "degraded": True,
                "note": f"state runner produced no JSON (exit {result.exit_code})"}
    return {"failures": data.get("failures", []), "degraded": False, "note": None}
```

- [ ] **Step 5: Register in `server.py`**

```python
from axon.tools.inspect_run import inspect_test


@app.tool(name="inspect")
def inspect(repo: str, test_target: str, timeout: int = 120) -> dict:
    return inspect_test(repo, test_target, timeout)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_inspect.py tests/test_server_cli.py -v`
Expected: all PASS (server test may assert tool count — update it if it enumerates tools).

- [ ] **Step 7: Commit**

```bash
git add src/axon/_state_runner.py src/axon/tools/inspect_run.py src/axon/server.py tests/test_inspect.py
git commit -m "feat: inspect tool — runtime exception frames + locals (LDB-style)"
```

---

### Task 5: `repro` failure classification + excerpt (execution-feedback loop)

Otter-style: the agent iterates on repro tests fastest when the tool says *how* the test failed. Classify and excerpt.

**Files:**
- Modify: `src/axon/tools/repro.py`
- Test: `tests/test_repro.py`

**Interfaces:**
- Produces: `repro_scaffold` result gains `"failure_kind"` (one of `"assertion"`, `"exception:<Type>"`, `"collection-error"`, `"passes"`, `"timeout"`) and `"failure_excerpt"` (last ≤15 lines of `test_result["raw_tail"]`, stripped).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_repro.py`)

```python
def test_repro_classifies_exception(fixture_repo):
    from axon.tools.repro import repro_scaffold
    root = fixture_repo()
    body = (
        "from calc.core import divide\n\n"
        "def test_zero_division_repro():\n"
        "    divide(1, 0)\n"
    )
    result = repro_scaffold(str(root), "zero division", body)
    assert result["currently_fails"]
    assert result["failure_kind"] == "exception:ZeroDivisionError"
    assert "ZeroDivisionError" in result["failure_excerpt"]


def test_repro_classifies_passes(fixture_repo):
    from axon.tools.repro import repro_scaffold
    root = fixture_repo()
    body = "def test_trivial():\n    assert True\n"
    result = repro_scaffold(str(root), "trivial", body)
    assert result["failure_kind"] == "passes"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_repro.py -k classif -v`
Expected: FAIL (KeyError).

- [ ] **Step 3: Implement** — add to `repro.py`:

```python
_EXC_LINE_RE = re.compile(r"\b([A-Za-z_]\w*(?:Error|Exception))\b")


def _classify(result: dict) -> str:
    if result.get("timed_out"):
        return "timeout"
    if result["exit_code"] == 0 and result["failed"] == 0 and result["errors"] == 0:
        return "passes"
    tail = result.get("raw_tail", "")
    if "errors during collection" in tail or "collected 0 items" in tail:
        return "collection-error"
    if "AssertionError" in tail or re.search(r"^E?\s*assert\b", tail, re.MULTILINE):
        return "assertion"
    exc_names = [m for m in _EXC_LINE_RE.findall(tail) if m != "AssertionError"]
    if exc_names:
        return f"exception:{exc_names[-1]}"
    return "assertion" if result["failed"] else "collection-error"


def _excerpt(result: dict) -> str:
    lines = [l for l in result.get("raw_tail", "").splitlines() if l.strip()]
    return "\n".join(lines[-15:])
```

and in the return dict of `repro_scaffold`: `"failure_kind": _classify(result), "failure_excerpt": _excerpt(result),`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_repro.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/axon/tools/repro.py tests/test_repro.py
git commit -m "feat(repro): failure classification + excerpt for execution-feedback loops"
```

---

### Task 6: `rank_patches` tool — verify + rank candidate patches

Agentless-style: sampling several candidate patches then selecting by repro+regression evidence beats single-shot patching. Batch version of `verify_fix` that computes the baseline **once**, dedupes normalized patches, verifies each, ranks.

**Files:**
- Create: `src/axon/tools/rank_patches.py`
- Modify: `src/axon/server.py`
- Test: `tests/test_rank_patches.py` (new)

**Interfaces:**
- Consumes: `verify_fix` module helpers `_run_pytest`, `_apply_patch`, `_revert_patch`, `_is_git_repo`, `_passed`, `_failure_ids` (all module-level in `src/axon/tools/verify_fix.py`).
- Produces: `rank_patches(repo: str, patches: list[str], repro_test: str, timeout: int = 600, max_patches: int = 8) -> dict` returning
  `{"ranked": [{"patch_index": int, "verdict": str, "regressions": [str], "changed_lines": int, "duplicate_of": int | None}], "best_index": int | None, "repro_before": dict, "note": str | None}`.
  Verdict order (best first): `"pass"`, `"regressions"`, `"fix-does-not-fix"`, `"apply-failed"`. Ties: fewer regressions, then fewer changed lines, then lower index. `best_index` only set when top verdict is `"pass"`. If repro passes before any patch: `{"ranked": [], "best_index": None, "note": "repro-not-red", ...}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_rank_patches.py`)

```python
from __future__ import annotations

GOOD_PATCH = """--- a/calc/core.py
+++ b/calc/core.py
@@ -4,5 +4,7 @@
 def divide(a, b):
-    return a / b
+    if b == 0:
+        return None
+    return a / b
 
 def safe_divide(a, b):
"""

BAD_PATCH = """--- a/calc/core.py
+++ b/calc/core.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a + b
+    return a - b
 
"""


def test_rank_patches_prefers_working_patch(git_fixture_repo):
    from axon.tools.rank_patches import rank_patches
    root = git_fixture_repo()
    result = rank_patches(
        str(root), [BAD_PATCH, GOOD_PATCH],
        "tests/test_calc.py::test_divide_zero_returns_none", timeout=120,
    )
    assert result["best_index"] == 1
    assert result["ranked"][0]["patch_index"] == 1
    assert result["ranked"][0]["verdict"] == "pass"
    # worktree restored
    assert "return a / b" in (root / "calc" / "core.py").read_text()


def test_rank_patches_dedupes_identical_patches(git_fixture_repo):
    from axon.tools.rank_patches import rank_patches
    root = git_fixture_repo()
    result = rank_patches(
        str(root), [GOOD_PATCH, GOOD_PATCH],
        "tests/test_calc.py::test_divide_zero_returns_none", timeout=120,
    )
    dupes = [r for r in result["ranked"] if r["duplicate_of"] is not None]
    assert len(dupes) == 1 and dupes[0]["duplicate_of"] == 0
```

Note: the fixture test `test_divide_zero_returns_none` asserts `divide(1, 0) is None`, so GOOD_PATCH turns it green; BAD_PATCH breaks `test_add` (regression) and does not fix the repro.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rank_patches.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `rank_patches.py`**

```python
"""Verify and rank multiple candidate patches against a repro test."""

from __future__ import annotations

from pathlib import Path

from axon.tools.verify_fix import (
    _apply_patch, _failure_ids, _is_git_repo, _passed, _revert_patch, _run_pytest,
)

_VERDICT_ORDER = {"pass": 0, "regressions": 1, "fix-does-not-fix": 2, "apply-failed": 3}


def rank_patches(repo: str, patches: list[str], repro_test: str,
                 timeout: int = 600, max_patches: int = 8) -> dict:
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
            entries.append({"patch_index": idx, "verdict": "duplicate",
                            "regressions": [], "changed_lines": _changed_lines(patch),
                            "duplicate_of": normalized_seen[norm]})
            continue
        normalized_seen[norm] = idx
        entries.append(_verify_one(root, patch, idx, repro_test, timeout, method, baseline_failures))

    unique = [e for e in entries if e["verdict"] != "duplicate"]
    unique.sort(key=lambda e: (_VERDICT_ORDER[e["verdict"]], len(e["regressions"]),
                               e["changed_lines"], e["patch_index"]))
    dupes = [e for e in entries if e["verdict"] == "duplicate"]
    ranked = unique + dupes
    best = ranked[0]["patch_index"] if ranked and ranked[0]["verdict"] == "pass" else None
    return {"ranked": ranked, "best_index": best, "repro_before": repro_before, "note": None}


def _verify_one(root: Path, patch: str, idx: int, repro_test: str, timeout: int,
                method: str, baseline_failures: set[str]) -> dict:
    apply_result = _apply_patch(root, patch, method)
    if apply_result["exit_code"] != 0:
        return {"patch_index": idx, "verdict": "apply-failed", "regressions": [],
                "changed_lines": _changed_lines(patch), "duplicate_of": None}
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
    return {"patch_index": idx, "verdict": verdict, "regressions": regressions,
            "changed_lines": _changed_lines(patch), "duplicate_of": None}


def _normalize(patch: str) -> str:
    lines = [l.rstrip() for l in patch.splitlines()
             if not l.startswith("index ") and l.strip()]
    return "\n".join(lines)


def _changed_lines(patch: str) -> int:
    return sum(1 for l in patch.splitlines()
               if (l.startswith("+") or l.startswith("-"))
               and not l.startswith("+++") and not l.startswith("---"))
```

Ranking places `"duplicate"` entries after unique ones (they carry `duplicate_of` so the agent can map back).

- [ ] **Step 4: Register in `server.py`**

```python
from axon.tools.rank_patches import rank_patches as rank_patches_tool


@app.tool(name="rank_patches")
def rank_patches(repo: str, patches: list[str], repro_test: str, timeout: int = 600) -> dict:
    return rank_patches_tool(repo, patches, repro_test, timeout)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_rank_patches.py tests/test_verify_fix.py -v`
Expected: all PASS (verify_fix untouched; helpers imported only).

- [ ] **Step 6: Commit**

```bash
git add src/axon/tools/rank_patches.py src/axon/server.py tests/test_rank_patches.py
git commit -m "feat: rank_patches tool — batch patch verification + evidence ranking"
```

---

### Task 7: `investigate` composite tool — one-call evidence bundle + guided workflow

Mid-tier models orchestrate many tool calls poorly. One call gathers what a senior dev would: localization (with functions), runtime state, source snippets, callers, recent-commit context — plus an explicit next-step workflow. Char-budgeted.

**Files:**
- Create: `src/axon/tools/investigate.py`
- Modify: `src/axon/server.py`
- Test: `tests/test_investigate.py` (new)

**Interfaces:**
- Consumes: `localize()` (Task 2 shape with `functions`), `inspect_test()` (Task 4), `ContextProvider.graph_context`, `RepoIndex`.
- Produces: `investigate(provider, index, repo: str, bug_text: str, failing_test: str | None = None, k: int = 5, budget_chars: int = 12000) -> dict` returning
  `{"suspects": [...localize suspects...], "runtime": dict | None, "snippets": [{"file","qualname","line","code"}], "graph": [{"qualname","callers":[...≤5]}], "recent_commits": [str ≤5], "workflow": [str], "truncated": bool}`.
- MCP: `@app.tool(name="investigate") def investigate(repo, bug_text, failing_test=None, k=5) -> dict`.

- [ ] **Step 1: Write the failing tests** (`tests/test_investigate.py`)

```python
from __future__ import annotations

from axon.index import RepoIndex
from axon.providers.builtin import BuiltinProvider


def _setup(root):
    provider = BuiltinProvider(root)
    provider.index(root)
    index = RepoIndex(root)
    index.refresh()
    return provider, index


BUG = (
    "divide crashes on zero\n"
    'Traceback (most recent call last):\n'
    '  File "calc/core.py", line 5, in divide\n'
    "ZeroDivisionError: division by zero\n"
)


def test_investigate_bundles_evidence(fixture_repo):
    from axon.tools.investigate import investigate
    root = fixture_repo()
    provider, index = _setup(root)
    result = investigate(provider, index, str(root), BUG,
                         failing_test="tests/test_calc.py::test_divide_zero_returns_none")
    assert result["suspects"][0]["file"] == "calc/core.py"
    assert result["runtime"] and result["runtime"]["failures"]
    snippet_quals = [s["qualname"] for s in result["snippets"]]
    assert "divide" in snippet_quals
    snippet = next(s for s in result["snippets"] if s["qualname"] == "divide")
    assert "return a / b" in snippet["code"]
    assert any("repro" in step for step in result["workflow"])


def test_investigate_without_failing_test(fixture_repo):
    from axon.tools.investigate import investigate
    root = fixture_repo()
    provider, index = _setup(root)
    result = investigate(provider, index, str(root), BUG)
    assert result["runtime"] is None
    assert result["suspects"]


def test_investigate_respects_budget(fixture_repo):
    import json
    from axon.tools.investigate import investigate
    root = fixture_repo()
    provider, index = _setup(root)
    result = investigate(provider, index, str(root), BUG, budget_chars=2000)
    assert result["truncated"] is True
    assert len(json.dumps(result)) <= 4000  # budget applies to evidence sections
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_investigate.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `investigate.py`**

```python
"""Composite evidence bundle: localize + runtime state + snippets + graph + history."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from axon.index import RepoIndex
from axon.providers.base import ContextProvider
from axon.tools.inspect_run import inspect_test
from axon.tools.localize import localize

_WORKFLOW = [
    "1. Read suspects + runtime state; pick the most likely function and state a one-line root-cause hypothesis.",
    "2. If no failing test exists, write one with the `repro` tool and check failure_kind matches the bug.",
    "3. If the hypothesis is unconfirmed, call `inspect` on the failing test and check the locals contradict/support it.",
    "4. Write a minimal patch for the hypothesized function only.",
    "5. Verify with `verify_fix` (single patch) or `rank_patches` (multiple candidates); only report verdicts that pass.",
]


def investigate(provider: ContextProvider, index: RepoIndex, repo: str, bug_text: str,
                failing_test: str | None = None, k: int = 5,
                budget_chars: int = 12000) -> dict:
    root = Path(repo).resolve()
    loc = localize(provider, index, bug_text, k, failing_test)
    suspects = loc["suspects"]
    runtime = inspect_test(str(root), failing_test) if failing_test else None

    top_functions: list[tuple[str, dict]] = []
    for suspect in suspects[:3]:
        for fn in suspect.get("functions", [])[:2]:
            top_functions.append((suspect["file"], fn))
    snippets = [_snippet(root, file, fn) for file, fn in top_functions[:4]]
    snippets = [s for s in snippets if s is not None]

    graph = []
    for _, fn in top_functions[:3]:
        name = fn["qualname"].split(".")[-1]
        ctx = provider.graph_context(name)
        callers = [f'{c["file"]}:{c.get("caller", "?")}' for c in ctx.callers[:5]]
        graph.append({"qualname": fn["qualname"], "callers": callers})

    result = {
        "suspects": suspects,
        "runtime": runtime,
        "snippets": snippets,
        "graph": graph,
        "recent_commits": _recent_commits(root),
        "workflow": list(_WORKFLOW),
        "truncated": False,
    }
    return _enforce_budget(result, budget_chars)


def _snippet(root: Path, file: str, fn: dict) -> dict | None:
    target = (root / file).resolve()
    if not target.is_relative_to(root):
        return None
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    start = max(fn["line"] - 1, 0)
    end = min(fn["end_line"], start + 40, len(lines))
    code = "\n".join(lines[start:end])
    return {"file": file, "qualname": fn["qualname"], "line": fn["line"], "code": code}


def _recent_commits(root: Path, limit: int = 5) -> list[str]:
    try:
        proc = subprocess.run(["git", "log", "--oneline", f"-n{limit}"],
                              cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def _enforce_budget(result: dict, budget_chars: int) -> dict:
    # Drop lowest-value evidence first until the bundle fits.
    for section in ("recent_commits", "graph", "runtime", "snippets"):
        if len(json.dumps(result)) <= budget_chars:
            break
        result[section] = [] if isinstance(result[section], list) else None
        result["truncated"] = True
    if len(json.dumps(result)) > budget_chars:
        result["suspects"] = result["suspects"][:3]
        result["truncated"] = True
    return result
```

- [ ] **Step 4: Register in `server.py`**

```python
from axon.tools.investigate import investigate as investigate_tool


@app.tool(name="investigate")
def investigate(repo: str, bug_text: str, failing_test: str | None = None, k: int = 5) -> dict:
    provider = _provider(repo)
    index = _repo_index(provider, Path(repo))
    return investigate_tool(provider, index, repo, bug_text, failing_test, k)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_investigate.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/axon/tools/investigate.py src/axon/server.py tests/test_investigate.py
git commit -m "feat: investigate tool — one-call evidence bundle with guided workflow"
```

---

### Task 8: Eval Function@k, docs, version 0.3.0

**Files:**
- Modify: `eval/run_localize_eval.py` — report Function@k next to File@k.
- Modify: `README.md` — tool list 11 → 14 (`inspect`, `rank_patches`, `investigate`), one-line descriptions.
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — `0.2.1` → `0.3.0` (marketplace.json has two version fields).
- Test: full suite.

**Interfaces:**
- Produces: eval prints `File@k` and `Function@k` per repo and overall. Gold functions parsed from the gold patch hunk headers: `re.compile(r"^@@ .* @@ (?:async )?def (\w+)", re.MULTILINE)` per `diff --git` file section; an instance counts as a Function@k hit when any suspect in top-k has a `functions` entry whose `qualname` last segment matches a gold function name for that gold file. Instances with no parseable gold function are excluded from the Function@k denominator (reported as `n_fn`).

- [ ] **Step 1: Extend eval** — in `eval_instance`, alongside file hits:

```python
_HUNK_DEF = re.compile(r"^@@[^@]*@@ .*?(?:async )?def (\w+)", re.MULTILINE)
_FILE_SPLIT = re.compile(r"^diff --git a/(\S+) b/\S+$", re.MULTILINE)


def gold_functions(patch: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    sections = _FILE_SPLIT.split(patch)
    # sections = [prefix, file1, body1, file2, body2, ...]
    for i in range(1, len(sections) - 1, 2):
        file, body = sections[i], sections[i + 1]
        if not file.endswith(".py"):
            continue
        for name in _HUNK_DEF.findall(body):
            out.add((file, name))
    return out
```

and count a Function@k hit when, for any suspect in top-k, `(suspect_file_matching_gold, fn.qualname.split(".")[-1])` is in the gold set. Print both metrics in the summary table.

- [ ] **Step 2: Update README + versions** — tools line becomes:

```
`axon serve` exposes 14 tools over MCP (stdio): `index`, `graph_context`,
`search`, `localize`, `run_tests`, `repro`, `verify_fix`, `spectrum`,
`sast_scan`, `refute`, `triage`, `inspect`, `rank_patches`, `investigate`.
```

Add a short "v0.3" bullet list under Status: function-level localization, runtime-state inspection, patch ranking, investigate bundle.

- [ ] **Step 3: Full suite**

Run: `python -m pytest -q`
Expected: all PASS (was 44; now ≥55).

- [ ] **Step 4: Commit**

```bash
git add eval/run_localize_eval.py README.md pyproject.toml .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "feat: v0.3.0 — Function@k eval, docs, version bump"
```

---

## Self-Review Notes

- Spec coverage: recency ✔ (T1), function-level localization ✔ (T2), spectrum upgrades ✔ (T3), runtime inspection ✔ (T4), repro feedback ✔ (T5), patch ranking ✔ (T6), composite investigate ✔ (T7), eval/docs/version ✔ (T8).
- Type consistency: suspect `functions` entries `{qualname, line, end_line, score}` produced in T2, consumed by T7 (`fn["qualname"]`, `fn["line"]`, `fn["end_line"]`) and T8 eval. `inspect_test` shape produced in T4, consumed as `result["runtime"]["failures"]` in T7. `verify_fix` helper names verified against current source.
- Known risk: `pytest_exception_interact` locals access — pinned fallback `excinfo.value.__traceback__` documented in T4. Sandbox venv must have pytest (existing `ensure_venv` handles it; `run_tests._has_pytest` fallback pattern available if needed).
