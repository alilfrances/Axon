# Phase 3 Spec — verification loop: `repro_scaffold`, `verify_fix`, spectrum FL

Division of labor: the CALLING agent writes test bodies and patches (it's the
LLM); Axon scaffolds, executes, measures, and never lies about results.

## src/axon/tools/repro.py

`repro_scaffold(repo: str, bug_slug: str, test_body: str | None = None) -> dict`
- Creates `tests/axon_repro/test_repro_<slug>.py` in the target repo
  (slug sanitized `[a-z0-9_]`, collision → suffix _2).
- If test_body given: write it verbatim (must contain `def test_`; else error
  dict, nothing written). If not given: write a skeleton with TODO comment and
  `pytest.fail("repro not implemented")` so it's red by construction.
- Then run ONLY that file via run_tests(test_target=...).
- Returns {test_file, run: <run_tests dict>, is_red: bool} — is_red True when
  the repro currently fails (desired state before a fix).

## src/axon/tools/verify_fix.py

`verify_fix(repo: str, patch: str, repro_test: str, timeout: int = 600) -> dict`
- patch = unified diff. Apply via `git apply --check` then `git apply` if repo
  is a git repo, else pure-Python fallback ONLY for simple single-file diffs
  (reject others with clear error). Record applied=True/False + method.
- Sequence: (1) run repro_test before patch → must be RED (if green, return
  {verdict: "repro-not-red"} and do NOT apply); (2) apply patch; (3) run
  repro_test → RED→GREEN? (4) run full suite → regression count vs a baseline
  full-suite run captured in step 1.
- ALWAYS revert the patch afterward unless keep=True param — verify_fix
  verifies, it does not commit. Revert via `git apply -R` / restore backup.
- Returns {verdict: "pass" | "fix-does-not-fix" | "regressions" |
  "repro-not-red" | "apply-failed", repro_before, repro_after,
  regressions: [test_id...], applied, reverted}.

## src/axon/tools/spectrum.py  (the Phase-2 hook lands here)

`spectrum_localize(repo: str, failing_tests: list[str],
passing_tests: list[str] | None = None, top: int = 20) -> dict`
- Runs each test via sandbox python with stdlib `trace.Trace(count=1)` through
  a small runner script (`python -m axon._trace_runner <test_id>`) that executes
  pytest programmatically and dumps {file: [lines]} JSON of repo-local lines
  executed. Skip site-packages/stdlib paths.
- If passing_tests None: auto-pick up to 3 green tests from last run_tests
  parse (or run `--collect-only` and sample). Fewer is fine; handle zero.
- Ochiai per line: ef/sqrt((ef+nf)*(ef+ep)); ef/ep = executed by
  failing/passing, nf = failing tests not executing it. Aggregate top lines.
- Returns {suspects: [{file, line, score}], method: "ochiai-trace"}.
- Wire into localize(): if failing_test given AND spectrum data obtainable,
  fuse spectrum list into RRF with weight 2.0, evidence "spectrum ochiai".
  Failure to trace → degrade silently to Phase-2 behavior + note in output.

## Server tools
Register `repro_scaffold`, `verify_fix`, `spectrum_localize` in server.py.

## Tests — tests/test_repro.py, test_verify_fix.py, test_spectrum.py
Fixture: calc repo IS a git repo now (conftest: git init + commit, set
user.email/name locally) — needed by verify_fix.
- repro: scaffold with body → file created, red detected; without body →
  skeleton red; bad body (no def test_) → error, no file.
- verify_fix happy path: planted divide bug (`return a / b` no zero-guard),
  repro test asserting divide(1,0) returns None (or raises custom error),
  patch fixing core.py → verdict "pass", reverted afterward (git status clean).
- verify_fix bad patch (doesn't fix) → "fix-does-not-fix", reverted.
- verify_fix patch breaking another test → "regressions" lists it, reverted.
- spectrum: failing test executes divide → core.py divide lines score > api-only
  lines; missing/uncollectable tests → graceful degrade dict, no crash.

Constraints: suite still fast — spectrum tests may take up to ~5s each (venv
reuse, no pip installs in-test: monkeypatch ensure_venv → sys.executable).
No new deps (stdlib trace; do NOT add coverage.py).
