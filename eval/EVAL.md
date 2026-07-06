# Axon Frozen Evaluation Definition (Phase 0)

Frozen before any implementation code. Changing these sets after tuning = overfitting; don't.

## Metrics (from docs/PLAN.md §1)

| Metric | Role | Target |
|---|---|---|
| File@3 localization | GATE | ≥90% |
| Function-level@3 | reported | — |
| Vuln precision | GATE | ≥90% |
| Vuln recall | reported | ≥70% |
| Verified-fix rate (repro-having) | bonus | ≥90% |

## Set A — Debugging: SWE-bench Verified subset (Python)

- Source: `princeton-nlp/SWE-bench_Verified` (HuggingFace).
- Slice: 60 instances, stratified by repo, selected by deterministic rule —
  sort instance_ids lexicographically per repo, take first N per repo
  proportional to repo share, seed-free and reproducible (`eval/select_swebench.py`).
- Split: 40 dev (tuning allowed) / 20 holdout (run once, at Phase 5 only).
- Ground truth for File@3: files touched by the gold patch.
- Runner note: SWE-bench harness needs Docker on the EVAL machine only.

## Set B — Security: PrimeVul Python slice

- Source: PrimeVul (paired vulnerable/patched functions), filtered to Python;
  supplement with CVEfixes Python commits if PrimeVul Python count < 150 pairs.
- Slice: 150 vulnerable + 150 patched (patched = negative class, measures FP).
- CWE focus (top Python classes): CWE-78 (command injection), CWE-89 (SQLi),
  CWE-79 (XSS), CWE-22 (path traversal), CWE-502 (deserialization),
  CWE-327 (weak crypto), CWE-798 (hardcoded creds).
- Split: 200 dev / 100 holdout, same discipline as Set A.
- Precision = TP / (TP+FP) over *reported* findings after refute.
  Recall = TP / all labeled vulns in slice.

## Fixture micro-suite (CI-runnable, no Docker, no dataset download)

`tests/fixtures/` — small planted-bug and planted-vuln repos. These verify the
machinery per phase. They are NOT the benchmark; numbers reported from fixtures
are smoke signals only and must be labeled as such.

## Cost budget (set now, enforced Phase 5)

- Dev eval run (Set A dev 40): ≤ $15 / run, ≤ 45 min wall.
- Full eval (both sets, holdout): ≤ $60 / run.
- Per-instance ceiling: ≤ $0.50 median, ≤ $1.50 p95 (kills runaway agent loops).
- Track: tokens + $ + wall time per instance from Phase 1 onward.
