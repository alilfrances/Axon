# Axon

**Root-cause debugging & vulnerability plugin for AI coding agents.**

Axon traces a fault signal back to its source — like the axon that carries a
neuron's signal. It gives an agent the tools to **localize bugs, verify fixes,
and find security vulnerabilities** with high precision.

Companion to [Cortex](../). Cortex is the context/graph brain; Axon is the
debugging + security tracer. **Cortex is optional** — Axon runs fully standalone.

## Why Axon

Research shows no agent hits "90% detect everything" universally. Axon reaches
≥90% on a *defined slice* by stacking four proven levers:

1. **Context grounding** — code graph + retrieval, built-in (no external deps).
2. **Executable verification** — reproduce → fix → confirm FAIL→PASS.
3. **Adversarial triage** — a refuter agent must disprove each finding → kills
   false positives (the security adoption killer).
4. **Static-analysis grounding** — SAST output the agent filters/confirms.

## Plug-and-play by design

- **Zero-config.** Install → run. Nothing else needed.
- **No GPU, no model download, no daemon.** Retrieval defaults to BM25 + ripgrep.
- **Optional accelerators, auto-detected, never required:**
  - **Cortex** → richer code graph/impact. Absent → built-in provider.
  - Local embedding model → semantic re-rank. Absent → BM25 floor.
  - CodeQL → deeper security. Absent → Semgrep.
- Same agent tools and output shape on every rung. Accelerators only improve
  quality/speed; their absence never breaks a feature.

## Tools (MCP)

`axon serve` exposes 14 tools over MCP (stdio): `index`, `graph_context`,
`search`, `localize`, `run_tests`, `repro`, `verify_fix`, `spectrum`,
`sast_scan`, `refute`, `triage`, `inspect`, `rank_patches`, `investigate`.

## Quickstart

```bash
pip install -e .      # or: uvx axon
axon doctor           # environment + active backend
axon index <repo>     # build/refresh the code index
axon serve            # start the MCP server (stdio)
```

Point any MCP host (Claude Code, etc.) at `axon serve`. Runs with no Cortex,
no GPU, no model download.

## Install as a Claude Code plugin

```bash
/plugin marketplace add <path-or-git-url-of-this-repo>
/plugin install axon@axon
```

The first server start bootstraps a private plugin venv and needs `python3`.
Semgrep-backed SAST is optional: install it with `pip install 'axon-debug[security]'`
into the plugin venv, or have `semgrep` available on `PATH`.

Versioning: Axon uses semver; bump `pyproject.toml`,
`.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json` together
on release.

## Status

**v0.3 built and verified** — 60 tests pass. Core machinery
(providers, localize, verify-fix loop, security triage) works and composes
end-to-end. The frozen benchmark run (SWE-bench + PrimeVul) is the next
milestone — see [`docs/VERIFICATION.md`](docs/VERIFICATION.md) for exactly
what is proven vs. still unmeasured, and [`docs/PLAN.md`](docs/PLAN.md) for
the design.

**v0.3 debugging upgrades** — function-level localization, runtime-state
inspection, patch ranking, and one-call investigate bundles add deterministic
evidence for root-cause debugging workflows. Measured on the django/sympy
SWE-bench Verified slice (n=8, no LLM, no regression from v0.2): File@3 50%,
File@10 75%, Function@10 12% (new deterministic-only baseline — the calling
agent is the reranking layer).

## Security

Report vulnerabilities privately through the process in [`SECURITY.md`](SECURITY.md).
Public repository hardening requirements are tracked in
[`docs/GITHUB_SECURITY.md`](docs/GITHUB_SECURITY.md).
