# Axon — Verification Report

Overnight autonomous build, 2026-07-07. Six phases, one commit each. Every
phase independently verified by the coordinator (not trusting subagent reports)
before commit.

## Build ledger

| Phase | Commit | What | Verification |
|---|---|---|---|
| 0 | `ac56340` | Eval sets, metrics, budget frozen; plan → stdlib-ast v0 | Docs review |
| 1 | `4d54807` | Providers, sandbox, MCP server, CLI | 15 tests; standalone ladder (Cortex off → Builtin); real graph_context on Axon's own source |
| 2 | `fb2dbc8` | `localize` deterministic ranking | 18 tests; traceback frame ranks #1 with correct evidence; empty input → [] |
| 3 | `1a1a903` | `repro_scaffold`, `verify_fix`, spectrum FL | 26 tests; **revert safety invariant** proven (git clean + byte-identical restore) across all 3 verdicts |
| 4 | `aea5d72` | `sast_scan`, `refute`, `triage` | 35 tests; precision 6/6 = 100%, all FPs suppressed, no TP suppressed |
| 5 | (this) | Integration, review, report | 11 MCP tools registered; end-to-end pipeline composes |

## Security review (Phase 5)

Automated commit review flagged 2 real defects in `refute.py`; both fixed +
regression-tested:

- **Path traversal** — `refute` reads `finding["path"]`, which is agent-supplied
  (untrusted). Absolute paths and `../` escaped the repo. Now contained via
  `is_relative_to(root)`; escape → `path-invalid`, no file read.
- **Allowlist-semantic-escape** — `_is_sanitized` used substring matching, so a
  `# html.escape(` comment or a stray `?` could suppress a *real* vulnerability
  (false negative — the dangerous direction for a security tool). Now uses AST
  Call-node detection on the finding line; comments/strings can't spoof it.

Self-review (codex hit its session limit mid-review, so coordinator finished it):
verify_fix always reverts on git AND non-git repos (pure-Python fallback);
BM25 empty-corpus/empty-query return [] (no division); refute mode!=static
raises; cortex adapter falls back to builtin rather than crashing.

## What was measured (fixture smoke — NOT the frozen benchmark)

These come from the CI micro-fixtures (`tests/fixtures`, `conftest` vuln_repo),
which prove the machinery works. They are smoke signals, not benchmark numbers.

- **Localization:** planted-bug File@1 hit on fixture; traceback frames rank
  first with honest evidence strings.
- **Verify-fix:** RED→GREEN + regression detection + guaranteed revert.
- **Security precision:** 100% on planted fixture (0 FP leaked after triage).
- **Security recall:** ~86% on the harder inline probe — CWE-798 hardcoded-secret
  rule missed one variant. Recall is *reported, not gated* (plan §1); above the
  ≥70% target but the 798 rule needs strengthening.

## NOT yet done (honest gaps)

- **Frozen benchmark not run.** SWE-bench Verified subset + PrimeVul Python
  slice (eval/EVAL.md) require dataset download + Docker (SWE-bench harness)
  + LLM agent budget. The plumbing is built; the eval run is the next real
  milestone. All headline metrics (File@3 ≥90%, precision ≥90%, recall) are
  defined and measurable but UNMEASURED against the real sets.
- **No LLM in the loop yet.** Axon supplies deterministic evidence + candidate
  ranking; the calling agent is the reasoning layer. The 90% drivers
  (verify loop, adversarial triage) exist; end-to-end 90% is a claim to be
  *earned* by running the benchmark, not asserted.
- **CWE-798 rule recall gap** (above).
- **Container sandbox** is spec'd (opt-in) but v0 ships subprocess+venv only.
- **Multi-language:** Python-only v0; parser interface ready for tree-sitter.

## How to run

```bash
pip install -e .            # or: uvx axon
axon doctor                 # environment + active backend
axon index <repo>           # build/refresh index
axon serve                  # start MCP stdio server
python -m pytest            # 35 tests, ~21s, no network/Docker
```

Plug-and-play confirmed: runs with Cortex absent (Builtin backend), semgrep
resolved from the install venv, no GPU, no model download, no daemon.
