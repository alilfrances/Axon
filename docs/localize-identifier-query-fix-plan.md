# Localize — Identifier-Aware Query + God-File Norm + QML Def Fallback

Date: 2026-07-09 · Follows `313a6fb` (lexical-weight damping, per-file chunk
cap). QA repro: bug in `ui/qml/windows/settings/DeviceCardTagSelection.qml`,
`strong_identifiers = [DeviceCustomField, DeviceCardTagSelection,
forceActiveFocus]` correctly parsed, yet `localize` ranks `idevice.cpp`
(huge, unrelated file) #1 and never surfaces the culprit.

## What's already fixed (verify, don't redo)

- Per-file chunk cap (`builtin.py:101`, `_cap_hits_per_file(per_file=2)`) —
  landed in `313a6fb`.
- Lexical weight halving when `strong_identifiers` is **empty**
  (`localize.py:75-78`) — landed in `313a6fb`. Not applicable here:
  identifiers ARE present, so this branch doesn't fire.

## Gap 1 — query construction ignores strong_identifiers when text is verbose

`_search_candidates` (`localize.py:283-297`) sends raw `bug_text`
unconditionally. `_bm25_candidates` (`localize.py:300-318`) builds
`terms = [*(strong_identifiers*3), *(quoted*2), *(dotted*2), bug_text]` —
the full raw prose is still appended, so a long bug report's vocabulary
still dominates the query even when good identifiers exist.

**Fix** (`localize.py`):
1. When `signals["strong_identifiers"]` is non-empty, build a second
   query string `" ".join(strong_identifiers)` and run it through
   `provider.search` as an additional ranked list (`"ident_search"`),
   alongside (not replacing) the existing raw-text `search`/`bm25` lists.
   RRF fusion already merges lists by file/rank — adding this list lets a
   tight identifier query surface the right file even when raw-text search
   buries it, without discarding raw-text's contribution when identifiers
   are weak/wrong.
2. Give `ident_search` a weight >= `search` (e.g. 1.4) in `_WEIGHTS`, since
   it's a strictly higher-precision query than the prose fallback.
3. Do NOT remove the existing raw-text `bug_text` term from `_bm25_candidates`
   — just stop relying on it alone. The new list is additive.

## Gap 2 — cross-file score normalization lets one god-file crush everyone

`_score_norms` (`localize.py:511-521`) is min-max normalized over the
*entire* candidate pool for a source. One file with raw score 552 sets
`hi`, so a correct file scoring e.g. 8 gets `norm ~0.01` even after the
per-file chunk cap limits *count*. Cap alone doesn't fix magnitude.

**Fix** (`localize.py`, `_score_norms` or its caller):
- Replace pure min-max with a **rank-position-weighted** norm floor: when
  the top raw score is an outlier (e.g. `hi > 5 * median(values)`), clamp
  `hi` to a saner ceiling (e.g. `median * 3`) before normalizing, so
  everyone below the outlier isn't crushed to ~0. Keep the existing
  fallback (`_BM25_LOW_SCORE_THRESHOLD` singleton case) unchanged.
- Add a regression test: one god-file candidate with raw_score 10x the
  next-highest, one on-topic candidate with a modest-but-real score —
  assert the on-topic candidate's `score_norm` stays above a floor (e.g.
  `>= 0.3`) instead of collapsing near 0.

## Gap 3 — explicit filename-basename boost (own signal, not folded into path)

`_path_candidates`' component-matching might incidentally catch
`identifier == file basename` but it's summed into a noisy list with no
`raw_score`, at the mercy of confidence-tier ties against lexical noise.

**Fix** (`localize.py`):
- Add a new ranked list `"filename"`: for each `strong_identifier`, if it
  case-insensitively equals a file's basename stem (any extension, not
  just `.py` — this must be language-agnostic for `.qml`/`.cpp`/etc.),
  emit that file as rank 1 with `evidence: "identifier matches filename"`.
- Weight it high (e.g. 2.0, between `path` 2.5 and `symbol` 1.5) — it's a
  near-certain signal when it fires (component-name-to-file convention is
  strong in QML/most single-definition-per-file languages).

## Gap 4 — QML graph def resolves to usage site (defensive stopgap only)

Root cause is upstream in Cortex (`source_ref` on the matched
`cortex_search_symbols` node points at the usage site, not the
declaration) — confirmed by code read of
`providers/cortex.py:247-303`&`353-399`, not an Axon fusion bug. A real
fix belongs in the Cortex repo.

**Stopgap fix (this repo only, defensive)** — `providers/cortex.py`,
`_graph_context_via_mcp` / `_graph_context_via_export`: when
`definitions` has more than one candidate node for a symbol, prefer the
one whose file basename stem (case-insensitive) equals the identifier
over other candidates, before falling back to the raw list order. Do
NOT filter definitions down to a single site — just reorder so the
basename-match sorts first. If exactly one definition exists (the common
case for non-QML), leave behavior unchanged.

**Separately**: file a ticket against `~/Personal Projects/Cortex`
describing the QML component-definition resolution bug (repro:
`DeviceCardTagSelection` definition edge resolves to
`DeviceCardDisplaySection.qml`, the usage site) — this stopgap does not
replace that fix.

## Acceptance test (add to `tests/test_localize.py`)

Given `bug_text` naming `DeviceCardTagSelection` + `forceActiveFocus` on
a repo containing `DeviceCardTagSelection.qml` and an unrelated large
file with high raw lexical overlap:
- `localize()["suspects"]` must contain `DeviceCardTagSelection.qml` in
  the top 3.
- The unrelated god-file must NOT be rank 1.
- If graph signal is exercised, assert the `"defines
  DeviceCardTagSelection (graph)"` evidence resolves to
  `DeviceCardTagSelection.qml`, not a usage-site file.

## Verification

- `pytest tests/test_localize.py tests/test_investigate.py -q` after each
  gap's change, keep all `313a6fb` assertions green.
- No version bump mid-slice; bump once at the end per repo convention.

## Scope note

In scope: `src/axon/tools/localize.py` (Gaps 1-3), `src/axon/providers/cortex.py`
(Gap 4 stopgap only), `tests/test_localize.py`. Out of scope: real Cortex-repo
QML resolution fix (separate ticket), full semantic/embedding search fallback.
