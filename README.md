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

## Status

Planning. See [`docs/PLAN.md`](docs/PLAN.md) — phased build with 6 stop points.
