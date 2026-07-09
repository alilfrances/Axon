# Axon — Root-Cause Debugging & Vulnerability Plugin

> Historical planning document, preserved as written. Packaging, dependency,
> and milestone details below reflect the plan at the time of writing, not the
> live `0.5.11` release state as of 2026-07-09.

> **Axon** traces a fault signal back to its source — the way an axon carries a
> neuron's signal. Companion to **Cortex** (Cortex = context/graph brain; Axon =
> the debugging + security tracer). Cortex optional, never required.
>
> Goal: give agents the tooling to reach **≥90% root-cause quality** on a
> *defined slice* of bugs and security vulnerabilities. Not a universal 90%.
>
> Design creed: **plug-and-play on any machine.** Zero-config, no GPU, no model
> download, no daemon. Heavy features are opt-in upgrades, never the baseline.

---

## 0. Reality Check (research-grounded)

| Task | SOTA today | Source |
|---|---|---|
| End-to-end fix **with oracle test** | ~95% (Fable 5 / Mythos 5, SWE-bench Verified) | [leaderboard](https://leaderboard.steel.dev/leaderboards/swe-bench-verified/) |
| Root-cause **localization, no oracle** | ~70% file-level; 20–32% exact top-3 | [Agentless](https://arxiv.org/pdf/2407.01489), [study](https://arxiv.org/pdf/2505.19489) |
| Localization + doc-augmented retrieval | 59.8% top-5 | [RepoRepair](https://arxiv.org/pdf/2603.01048) |
| Vuln detection raw | 78–85% | [study](https://arxiv.org/pdf/2605.23243) |
| Vuln false positives | 92% → 6.3% with LLM filtering | [FP study](https://arxiv.org/html/2601.22952v1) |
| Adversarial multi-agent precision | high-precision defect discovery | [Refute-or-Promote](https://arxiv.org/pdf/2604.19049) |

**Conclusion:** 90% is reachable IF we (a) narrow scope, (b) add executable
verification, (c) ground context via code graph/retrieval, (d) use adversarial
triage to crush false positives. Chasing "detect everything" fails.

---

## 1. Success Metrics (LOCKED)

Headline = **A + C**. B is a bonus signal where repro exists.

- **Target A — Localization@3, FILE-level (gate):** correct root-cause **file**
  in top-3. Goal: **≥90%** on the benchmark slice. Function-level hit rate is
  *reported alongside* but not gated — §0 shows exact function top-3 SOTA is
  20–32%; gating on it would make the headline unfalsifiable. File@3 ≥90% is
  the honest, reachable bar (file-level SOTA ~70%; graph + retrieval + rerank
  closes the gap).
- **Target B — Verified-fix rate (bonus):** reproduce → patch → FAIL→PASS.
  Goal: ≥90% *on issues that ship or admit a repro*. Non-gating (§7).
- **Target C — Vuln precision (gate) + recall (reported):**
  - **Precision ≥90%** on reported findings — the adoption gate. Achievable via
    adversarial triage (FP 92%→6.3% evidence, §0).
  - **Recall reported, target ≥70%** on the labeled CWE slice. **90% recall is
    NOT claimed** — §0 raw detection tops out 78–85%; no system hits 90% recall
    on arbitrary code. Anyone gating on 90% recall is overfitting or lying.

Plain reading of "90% root-cause quality": **≥90% of what Axon reports is the
real root cause / a real vuln, and ≥90% of the time the true file is in its
top-3.** Not "finds 90% of all bugs that exist."

---

## 2. Architecture — Four Pillars

1. **Context grounding** — code graph + retrieval, behind a **provider interface**.
   Plugin ships its own **built-in fallback** (see §2.1) so it works standalone.
   If Cortex is installed, an adapter uses it for richer graph/impact. Either
   way the agent sees callers/callees/impact, not raw file dumps.
2. **Executable verification** — sandbox that reproduces the bug, runs tests,
   confirms fix. Ground truth beats model opinion. Biggest single lever.
3. **Adversarial triage** — proposer agent finds candidates; refuter agent must
   disprove each. Only survivors reported. Kills false positives.
4. **Static-analysis grounding (security)** — wrap SAST output (Semgrep default,
   CodeQL opt-in), let agent filter/confirm. LLM filtering drops FP 92%→6.3%.

### 2.1 Context Provider — standalone by default, Cortex-accelerated

The plugin MUST run with **zero external graph deps**. Context grounding sits
behind one interface with pluggable backends, auto-selected at runtime:

```
ContextProvider (interface)
  ├─ graph_context(symbol) -> {def, callers, callees, blast_radius}
  ├─ search(query)         -> ranked file:line snippets
  └─ index(repo)           -> build/refresh backend index

Backends (auto-detected, best available wins):
  1. CortexProvider   — if `cortex` CLI / Cortex MCP present. Richest.
  2. BuiltinProvider  — DEFAULT. Ships with plugin. No external deps.
  3. GrepProvider     — last-resort floor. ripgrep + ctags only.
```

**BuiltinProvider** (the standalone engine, always available):
- Parse repo → symbol table. **v0: Python stdlib `ast`** (zero-dep, Python-first
  scope makes tree-sitter unnecessary now). Parser sits behind its own small
  interface; tree-sitter slots in at the multi-lang milestone without engine
  rewrite.
- Build lightweight call/import graph in local SQLite (`.dbgplugin/index.db`).
- **Retrieval default = BM25 + ripgrep. No embedding model, no GPU, no
  download.** This is the shipped baseline — pure CPU, tiny footprint.
- Semantic embeddings are an **opt-in upgrade** (`axon --semantic`): if a local
  embedding model is present, re-rank BM25 hits. Absent → BM25 stands alone,
  fully functional. Retrieval quality degrades gracefully, never breaks.
- Incremental refresh on file change; no server, no daemon required.

**Selection logic:** detect Cortex (CLI on PATH or MCP tool available) →
use it. Else build/reuse builtin index. Else GrepProvider. Log which backend
is active so results are reproducible. **Tool signatures and output schema are
identical on every rung; field richness degrades honestly** — e.g. GrepProvider
returns `blast_radius: []` with `degraded: true`, never a fake value. No
Cortex-specific code leaks past the adapter.

**Implementation language: Python.** Consequences: SQLite = stdlib (`sqlite3`,
nothing to vendor), tree-sitter via `py-tree-sitter` wheels, distribution via
`pip install axon` / `uvx axon`. ctags is NOT a hard dep — GrepProvider-only,
used if present.

---

## 3. Tools the Plugin Exposes to Agents

**Packaging: MCP server** (stdio) — works with Claude Code, Codex, Cursor, any
MCP host → maximum plug-and-play. A thin Claude Code plugin manifest wraps the
same server (adds skills/commands); the MCP server is the product.

- `repro_bug` — build repro harness / failing test from issue text.
- `graph_context` — symbol, callers, callees, blast radius. Served by whichever
  ContextProvider backend is active (Cortex → Builtin → Grep). Same output shape.
- `run_tests` — sandboxed test exec, structured pass/fail diff (sandbox model §5).
- `localize` — rank suspect file:line via graph + retrieval + LLM rerank.
  Spectrum-based FL is an *optional booster that activates only after Phase 3*
  ships test execution — it needs failing-test coverage data to exist.
- `sast_scan` — run Semgrep (bundled; CodeQL opt-in), normalize findings.
- `refute` — adversarial check: try to disprove a candidate finding.
  **Security findings: refutation is static/reasoning-based by default — Axon
  never executes exploit PoCs baseline.** PoC execution is opt-in, sandboxed,
  and requires explicit user consent per run.
- `verify_fix` — apply patch, confirm FAIL→PASS, no regressions.

---

## 4. Build Phases + STOP POINTS

### Phase 0 — Eval-set freeze  🛑 STOP 1
Metrics + tech decisions already locked (§1, §7). Remaining work: freeze the
concrete eval sets — pick the SWE-bench Verified subset (Python), and the
security slice from **PrimeVul / CVEfixes (Python CWEs)** (mainstream Java
benchmarks conflict with Python-first). Hold out a private split (§6 overfit
risk). Set cost budget per eval run NOW, not Phase 5.
**STOP: confirm frozen eval sets + budget before any code.**

### Phase 1 — Harness + standalone context + baseline  🛑 STOP 2
Wire plugin skeleton, `run_tests` sandbox, and the **ContextProvider interface
with BuiltinProvider working first** (tree-sitter + SQLite + BM25). Add
CortexProvider adapter + auto-detection *after* builtin is green. Verify plugin
runs end-to-end on a machine with **no Cortex installed**.
Measure baseline localization/fix with no special tooling. Track cost/latency
per run from day one.
Note: the plugin itself stays Docker-free, but the **SWE-bench eval harness is
Docker-based** — eval machine needs Docker; user machines never do.
**STOP: confirm standalone run works Cortex-free; review baseline — gap to 90%
plausible? Compare Builtin vs Cortex backend numbers if Cortex available.**

### Phase 2 — Localization pillar  🛑 STOP 3
Implement `localize` (graph + retrieval + LLM rerank; spectrum FL deferred to
Phase 3+ — needs test infra). Evaluate file-level top-3.
**STOP: report File@3 + function-level. Ladder: <75% → fix retrieval/graph;
75–90% → close gap with rerank ensembles + multi-candidate refute; the refute
step is expected to supply the final margin (§0 FP-filter evidence).**

### Phase 3 — Verification loop  🛑 STOP 4
Add `repro_bug` + `verify_fix`. Close the reproduce→fix→confirm cycle. Enable
spectrum FL booster for `localize` now that failing-test coverage exists.
**STOP: report verified-fix rate on repro-having issues.**

### Phase 4 — Security + adversarial triage  🛑 STOP 5
Add `sast_scan` (bundled Semgrep) + `refute`. Measure on the frozen PrimeVul/
CVEfixes Python slice; track FP rate.
**STOP: report precision (gate ≥90%) + recall (report, target ≥70%) + FP.**

### Phase 5 — Integration + hardening  🛑 STOP 6
Combine pillars end-to-end, full eval run, cost/latency budget.
**STOP: final report vs 90% target. Ship / iterate decision.**

---

## 5. Dependencies, Packaging & Sandbox (standalone-first)

- **Hard deps (installed with `pip install axon`):** **Semgrep** (pip dep — the
  default SAST engine must work on fresh install, so it ships as a dependency,
  not an accelerator) and the MCP SDK. Parsing = stdlib `ast` (v0), SQLite =
  stdlib. ripgrep used if on PATH, pure-Python scan fallback otherwise. All
  local, no network services. tree-sitter deferred to multi-lang milestone.
- **Optional accelerators (auto-detected, never required):**
  - **Cortex** — richer graph/impact via `CortexProvider`. Absent → BuiltinProvider.
  - Embedding model — semantic re-rank. Absent → BM25/ripgrep floor.
  - CodeQL — deeper security. Absent → Semgrep (always present).
  - ctags — GrepProvider floor enrichment. Absent → plain ripgrep.
- **Sandbox model (`run_tests` / `verify_fix`):** default = **subprocess +
  ephemeral venv** — zero extra install, works everywhere, honest limitation:
  process isolation only, not a security boundary. **Container backend
  (Docker/Podman) is opt-in** (`axon --sandbox=container`) for untrusted code
  and for exploit-PoC execution (§3 `refute` consent rule). Plug-and-play
  creed forbids making Docker the baseline.
- **Zero-config default:** `install → run` works with nothing but the plugin.
- **Degradation ladder is explicit and logged:** Cortex ▸ Builtin ▸ Grep;
  Embedding ▸ BM25; Container ▸ venv. Tool contract identical on every rung;
  degraded fields flagged, never faked.

## 6. Risks

- **Oracle-test dependence** — without repro, fix rate drops hard. Mitigate: make
  repro-generation a first-class tool; degrade gracefully to localization-only.
- **False positives (security)** — the adoption killer. Adversarial refute is
  mandatory, not optional.
- **Benchmark overfit** — hold out a private eval set; report on unseen repos.
- **Cost/latency** — multi-agent + sandbox is expensive. Budget set at Phase 0,
  tracked from Phase 1, enforced at Phase 5.

---

## 7. Decisions (locked — plug-and-play biased)

All decisions resolved toward the lightest option that works.

- **Metrics:** headline = **A (File@3 ≥90%, gate) + C (precision ≥90% gate,
  recall ≥70% reported)**. B bonus/non-gating. Full definitions §1.
- **Packaging:** MCP server (stdio), Python, `pip install axon` / `uvx axon`;
  Claude Code plugin manifest as thin wrapper (§3).
- **Sandbox:** subprocess + venv default; container opt-in (§5).
- **Security eval set:** PrimeVul / CVEfixes Python CWE slice (§ Phase 0).

- **Retrieval:** BuiltinProvider ships **BM25 + ripgrep only** — zero-dep, no GPU,
  no model download. Semantic embeddings are opt-in, not baseline.
- **Language scope:** **Python first.** Biggest benchmark coverage (SWE-bench),
  proves the pipeline fastest. tree-sitter grammars are tiny and vendored, so
  the architecture is multi-lang-ready — add JS/TS/Go later by dropping in a
  grammar, no engine rewrite. Ship narrow, grow cheap.
- **SAST engine:** **Semgrep default.** Single binary / pip, rule-based, runs
  instantly, no compile step. **CodeQL rejected as default** — it builds a
  compiled database per repo (slow, needs toolchain) which breaks plug-and-play.
  CodeQL stays an opt-in accelerator for users who already run it.
- **Verified-fix (Target B):** **in scope, but opt-in and non-gating.** When an
  issue ships a repro or Axon can synthesize one, run the reproduce→fix→confirm
  loop. When it can't, degrade to localization-only — no hard dependency on
  tests existing. Headline metric stays **A + C**; B is a bonus signal.

Net: install Axon, point at a Python repo, run. No models, no DB build, no
toolchain, no daemon, no Cortex. Everything heavier is an optional upgrade.
