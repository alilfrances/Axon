# Axon

**Root-cause debugging & vulnerability MCP server and CLI for AI coding agents.**

Axon traces a fault signal back to its source — like the axon that carries a
neuron's signal. It gives an agent the tools to **localize bugs, verify fixes,
and find security vulnerabilities** with high precision.

Companion to [Cortex](../). Cortex is the context/graph brain; Axon is the
debugging + security tracer. **Cortex is optional** — Axon runs fully standalone.

Current release facts (2026-07-09 docs refresh): package/plugin version
`0.5.11`; published distribution name `axon-debug`; executable name `axon`.

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
- **Dependency-light startup.** Plugin startup uses
  [`bin/axon-mcp.py`](bin/axon-mcp.py), which imports `axon.mcp_stdio`
  directly; no plugin-local `pip install` or venv bootstrap is required.
- **Optional accelerators, auto-detected, never required:**
  - **Cortex** → richer code graph/impact. Preferred transport is Cortex's
    MCP server (`cortex mcp`; override with `AXON_CORTEX_MCP_CMD`, set it to
    `off` to force the CLI), which reuses Cortex's persistent per-repo index.
    Falls back to the `cortex` CLI (per-call budgets tunable via
    `AXON_CORTEX_INGEST_TIMEOUT` / `_BUNDLE_TIMEOUT` / `_GRAPH_TIMEOUT`),
    then to the built-in provider — logging why it degraded.
  - `mcp` extra → FastMCP-based server path when you want it.
  - `semgrep` extra → Semgrep-backed SAST when you want it.
- Same agent tools and output shape on every rung. Accelerators only improve
  quality/speed; their absence never breaks a feature.

## Tools (MCP)

`axon serve` exposes Axon's MCP registry over stdio, including `index`,
`graph_context`, `search`, `status`, `localize`, `run_tests`, `repro`,
`verify_fix`, `rank_patches`, `spectrum`, `inspect`, `investigate`,
`sast_scan`, `refute`, and `triage`.

## Quickstart

```bash
pip install -e .      # or: uvx axon-debug
axon --help           # current subcommands: serve, index, doctor, gc
axon doctor           # environment + active backend
axon index <repo>     # build/refresh the code index
axon serve            # start the MCP server (stdio)
```

Point any MCP host (Claude Code, etc.) at `axon serve`. Runs with no Cortex,
no GPU, no model download.

## Install as a Claude Code plugin

Inside an interactive Claude Code session, use slash commands:

```bash
/plugin marketplace add "/path/to/Axon"
/plugin install axon@axon
```

From a shell, use the Claude Code CLI equivalents:

```bash
claude plugin marketplace add "/path/to/Axon"
claude plugin install axon@axon
```

You can substitute the Git remote if you prefer not to use the local clone path:
`https://github.com/alilfrances/Axon.git`

## Install as a Codex plugin

```bash
codex plugin marketplace add "/path/to/Axon"
codex plugin add axon@axon
```

Codex can use the same Git remote source instead of the local path:
`https://github.com/alilfrances/Axon.git`

Official command references: [Codex plugin marketplace CLI](https://developers.openai.com/codex/cli/reference#codex-plugin-marketplace), [Codex plugin install flow](https://developers.openai.com/codex/plugins/build#add-a-marketplace-from-the-cli), and [Claude Code plugin marketplaces](https://code.claude.com/docs/en/discover-plugins).

Start a new Claude Code or Codex session after installation so the plugin MCP server and hooks are loaded.

Plugin startup needs `python3` and does not run `pip` or create a venv.
`bin/axon-mcp.py` loads the dependency-free `axon.mcp_stdio` adapter directly.
Semgrep-backed SAST is optional: install `semgrep` on `PATH` to enable it.
Codex installs plugins into its local plugin cache; after updating Axon, run
`codex plugin marketplace upgrade axon` and restart Codex so the MCP server is
loaded from the refreshed cache.

Versioning: Axon uses semver; bump `pyproject.toml`,
`src/axon/__init__.py`, `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, and `.codex-plugin/plugin.json` together on
release.

## Status

Current package/plugin version is `0.5.11`. The repository's pytest suite now
contains 115 test functions. Older `v0.3` / `60 tests` statements are retained
only in dated planning or verification records.

See [`docs/VERIFICATION.md`](docs/VERIFICATION.md) for the dated verification
log and [`docs/PLAN.md`](docs/PLAN.md) for the original planning document.

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
