# Axon Integration Review — Findings & Fix Plan

Date: 2026-07-08 · Scope: Cortex integration, fallback behavior, ingest wait time, multi-language support, Codex plugin MCP setup.

## Review Summary

What works well today:

- **Provider ladder** (`providers/select.py`): cortex → builtin → grep, with `prefer` override. `axon index` CLI now uses the ladder (fixed in 1d09f12).
- **Cortex MCP transport** (`providers/cortex_mcp.py`): persistent `cortex mcp` stdio client, handshake validation, required-tool check, `missing_db` → `cortex_refresh` retry.
- **Degradation recording**: `index()` returns `fallback_reason`, `GraphContext` carries `backend` + `note`, builtin `_scope_note` explains "Python-only" on symbol miss.
- **Cortex path is language-agnostic**: Axon passes `cortex_query` / `cortex_search_symbols` / `cortex_references` / `cortex_relations` payloads through without language filtering, so C/C++, QML/Qt, and anything else Cortex indexes flows through fully.
- **Plugin manifests**: Claude (`.claude-plugin/`) and Codex (`.codex-plugin/` + `.agents/plugins/marketplace.json`) both present, version-locked by tests; launcher venv is writable-cache based (698674d).

## Findings (severity-ordered)

### F1 — stdout print corrupts MCP stdio protocol — HIGH
`providers/select.py:27` does `print(f"Axon provider: {provider.backend}", flush=True)` to **stdout**. `axon serve` runs FastMCP over stdio (`server.py:124`); provider selection happens lazily on first tool call, so this line is emitted mid-session into the JSON-RPC stream. Some clients tolerate stray lines; Codex/strict clients may not.
**Fix**: route to `sys.stderr` (same pattern as `_warn_fallback` in `cortex.py`). Audit repo for any other stdout prints reachable from `serve` (`cli.py` prints are fine — CLI only).

### F2 — Ingest timeout too low for large repos — HIGH
`cortex.py:31` `_DEFAULT_TIMEOUTS = {"ingest": 120, ...}` but real first-ingest on large repos is **3+ minutes**. Affects three call sites: `index()` via MCP `cortex_refresh`, `index()` via CLI `cortex ingest`, and the `missing_db` retry inside `_mcp_call`. On timeout Axon silently degrades to builtin — exactly the failure mode 4698560 tried to kill.
**Fix**:
- Raise default ingest timeout to **600s** (env override stays).
- Before a potentially-long `cortex_refresh`/`ingest`, print stderr notice: `"Axon: cortex ingest in progress (large repos can take several minutes)…"` so the user sees why the tool call is quiet.
- On timeout, keep the existing actionable message (raise `AXON_CORTEX_INGEST_TIMEOUT`).

### F3 — Fallback search is silently empty for non-Python repos — HIGH
Builtin index parses only `.py` (`parsing.py:45`), BM25 corpus builds only from indexed Python files, and `GrepProvider` also hardcodes `(".py",)` (`grep.py:99`). On a C/C++/Swift/Java/JS/QML repo with Cortex unavailable:
- `graph_context` → empty with a good note ✅
- `search` → **zero hits, no explanation** ❌
- `index` → stats show ~0 files, no language note ❌

**Fix (keeps symbol analysis Python-only, makes text retrieval language-agnostic)**:
- Add a shared `TEXT_EXTENSIONS` set covering `.c .h .cc .cpp .cxx .hpp .m .mm .swift .java .kt .js .jsx .ts .tsx .qml .go .rs .rb .php .cs` (+ existing `.py`).
- Builtin: file-level BM25 docs from all `TEXT_EXTENSIONS` files (symbol-level docs stay Python). Chunk long files as today.
- Grep provider: iterate `TEXT_EXTENSIONS`.
- Transparency: when search runs on fallback and repo contains non-Python sources, attach note/stat: `"builtin fallback: full-text search across N files; symbol graph is Python-only"`. Include in `index()` return dict and `axon status` output.

### F4 — Older Cortex without `cortex_relations` kills whole MCP transport — MEDIUM
`_callees_via_mcp` catches only `CortexMcpToolError`, but a server lacking the tool returns a JSON-RPC method error → `CortexMcpError` → propagates to `graph_context`'s handler → `_drop_mcp()` **permanently downgrades to CLI/builtin** just because the optional callees lookup failed. (`cortex_relations` is deliberately not in `_REQUIRED_TOOLS`.)
**Fix**: in `_callees_via_mcp`, catch `CortexMcpError` for the relations call only, log once, return `[]`. Do not drop the transport.

### F5 — Codex MCP setup: `${CLAUDE_PLUGIN_ROOT}` expansion unverified — MEDIUM
`.codex-plugin/plugin.json` → `"mcpServers": "./.mcp.json"` → `.mcp.json` args use `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/serve.sh`. `serve.sh` itself falls back to `CODEX_PLUGIN_ROOT` / script-relative path, but that only helps **if the script path in args resolves at all**. If Codex does not substitute `${CLAUDE_PLUGIN_ROOT}`, launch fails before serve.sh runs.
**Fix**:
1. Check official OpenAI/Codex plugin docs (per global rules) for which variables Codex expands in MCP config.
2. If Codex uses a different variable or none: either add a Codex-specific MCP config referenced from `.codex-plugin/plugin.json`, or make the entry robust (e.g. relative path resolution Codex supports).
3. Extend `tests/test_plugin_manifests.py` to assert the Codex-side path convention.
4. Manual smoke: install plugin in Codex, confirm `axon` MCP server handshakes and `status`/`search` tools respond.

### F6 — Cortex language coverage confirmation — LOW (verification, not code)
Cortex confirmed for Python/C/C++/QML+Qt (0.3.0+). **Swift and Java support is unconfirmed** in my notes. Axon needs no code change either way (pass-through), but the claim "fully uses Cortex for those languages" needs one check: run `cortex ingest` + `cortex_search_symbols` on a small Swift and Java sample. If Cortex lacks them, those repos ride F3's improved text fallback — which is exactly the transparent-degrade behavior wanted; document it in README.

### F7 — No visible backend/status surface over MCP — LOW
`axon status` CLI shows active backend, but agent-side (MCP) there is no cheap "which backend am I on and why" tool; degradation only shows in per-call fields.
**Fix**: add tiny `status` MCP tool returning `{backend, fallback_reason, python_files, text_files}`. Helps agents decide whether to trust graph results.

## Execution Order

| # | Task | Files | Size |
|---|------|-------|------|
| 1 | F1 stdout→stderr | `providers/select.py` | ~2 lines |
| 2 | F2 timeout 600s + progress notice | `providers/cortex.py` | ~10 lines |
| 3 | F4 relations error containment | `providers/cortex.py` | ~5 lines |
| 4 | F3 multi-language text fallback + notes | `parsing.py`, `index.py`, `providers/builtin.py`, `providers/grep.py` | ~60–80 lines |
| 5 | F7 status MCP tool | `server.py` | ~15 lines |
| 6 | F5 Codex MCP config verification + fix | `.codex-plugin/`, `.mcp.json`, manifest tests | docs-dependent |
| 7 | F6 Swift/Java Cortex check + README language matrix | `README.md`, `docs/` | verification |

## Verification

- Unit: new tests per fix (stderr capture for F1; timeout env for F2; fake MCP missing `cortex_relations` for F4 via `tests/fake_cortex_mcp.py`; multi-language fixture repo for F3; manifest assertions for F5). Full `pytest` suite must stay green (currently 62 tests).
- Live: rerun the v0.4.0 Cortex integration check on this repo (graph_context/search, no fallback); then rename `cortex` off PATH and confirm transparent fallback messages on a mixed-language sample.
- Codex: manual plugin install + MCP handshake smoke test.

## Open Questions (non-blocking, defaults chosen)

- F2 default 600s vs configurable-only: default 600s chosen — silent degrade is worse than a long wait.
- F3 extension list: fixed curated set chosen over "any text file" to avoid indexing lockfiles/minified JS.
