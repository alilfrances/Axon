Date: 2026-07-09 · Follows `f8ad43a` (identifier-weighted query, god-file
score-norm clamp, QML def basename preference). Real-repo retest (0.5.9):
culprit `DeviceCardTagSelection.qml` now #2 (was absent) but two gaps keep
it off #1 and let `idevice.cpp` stay top.

## Gap 1 — filename-match reads a Python-only file list, on every backend

`_filename_candidates` (`localize.py:287-295`) and `_path_candidates`
(`localize.py:241-279`) both read `index.conn.execute("SELECT path FROM
files")`. That table is populated by `RepoIndex.refresh()` walking
`iter_source_files(repo_root, self.parser.extensions)` — and `RepoIndex(repo)`
(`tool_registry.py:130`, `spectrum.py:136`) always defaults to
`PythonAstParser`, whose `extensions = (".py",)`. So `files` never contains
`.qml`/`.cpp`/etc. paths in production, on ANY provider backend — not just
cortex-mcp. The weight-2.0 filename signal silently no-ops for every
non-Python repo.

This is masked by the existing test: `test_localize_identifier_query_and_
filename_surface_qml_over_god_file` builds `RepoIndex(repo, parser=
TextFixtureParser())` — a custom parser with `.py`/`.qml`/`.cpp` extensions
that production code never passes. The test proves the fusion logic works
once the file list is right; it doesn't prove the file list is ever right.

**Fix** (`localize.py`):
1. Add a helper `_all_repo_files(index: RepoIndex) -> list[str]` that walks
   the filesystem directly via `iter_source_files(index.repo_root,
   TEXT_EXTENSIONS)` (both already exist in `axon.parsing`, already used the
   same way by `providers/grep.py`, `providers/builtin.py`, `tools/sast.py`)
   and returns paths relative to `index.repo_root` as strings, sorted.
2. Replace `index.conn.execute("SELECT path FROM files ...")` in both
   `_filename_candidates` and `_path_candidates` with this helper.
   `_path_candidates` shares the identical root cause (path-suffix/component
   matching also silently degrades to Python-only) — fix both, not just the
   one the QA repro happened to hit.
3. Do not remove or touch `index.conn`/`RepoIndex` itself — no parser
   change, no schema change. This is purely swapping the file-list source
   in these two functions.

**Regression test to add** (`tests/test_localize.py`): a variant of
`test_localize_identifier_query_and_filename_surface_qml_over_god_file`
that builds `RepoIndex(repo)` with **no parser override** (default
`PythonAstParser`) so the `files` table only has 0 rows for the qml/cpp
fixture files, and asserts the filename/path signals still fire (i.e. the
fix doesn't depend on the table). Keep the existing test as-is (still
exercises the fusion logic under the richer table).

## Gap 2 — god-file lexical outlier still wins after the median clamp

`idevice.cpp` (fused 0.036) still beats the culprit (0.022) even with
Gap 1 fixed, because of two compounding issues in `_fuse`/`_score_norms`
(`localize.py:97, 548-562`):

a. `_score_norms` clamps the *ceiling* (`hi = median * 3`) when one score is
   a >5x outlier, but the outlier itself still normalizes to `min(1.0, ...)`
   — i.e. the clamp compresses everyone else's headroom but never demotes
   the outlier's own `score_norm` below ~1.0. The clamp helps other
   candidates look less crushed; it does nothing to the god-file's score.

b. `_search_candidates` (`localize.py:303-317`) always sends the raw,
   unweighted `bug_text` to `provider.search`, at full `search` weight
   (1.2), even when `signals["strong_identifiers"]` is non-empty and
   `ident_search`/`filename` already cover that ground with higher
   precision. `lexical_weight_reduced` (`localize.py:77-80`) only damps
   `bm25`/`search` when identifiers are ABSENT — backwards from what's
   needed: verbose bug text with a large-file lexical false-positive is
   exactly the case where identifiers ARE present and the raw-text list is
   the noise source.

**Fix** (`localize.py`):
1. In `_score_norms`, when the outlier clamp fires (`hi > 5 * median`),
   cap the returned norm at a fixed ceiling below 1.0 (e.g. `0.6`) instead
   of `1.0`, for that source's whole list:
   ```python
   if median > 0 and hi > 5 * median:
       clamped_hi = max(lo, median * 3)
       return {cid: max(0.0, min(0.6, (score - lo) / (clamped_hi - lo)))
               for cid, score in scored}
   ```
   This directly demotes the outlier's own contribution rather than only
   rescaling everyone below it. Non-outlier lists are unaffected (still
   normalize to the full 0..1 range via the existing `return` below).
2. In `localize()`, when `signals["strong_identifiers"]` is non-empty,
   still damp `weights["search"]` (e.g. `*= 0.6`) — the plain raw-`bug_text`
   list — since `ident_search` (1.4) and `filename` (2.0) are the
   higher-precision replacements once identifiers exist. Do NOT damp
   `bm25` here: `_bm25_candidates` already folds `strong_identifiers * 3`
   into its own query terms, so it's not a "pure raw-prose" list the same
   way `search` is.

**Acceptance test** (extend
`test_localize_identifier_query_and_filename_surface_qml_over_god_file`,
plus the new Gap-1 regression test): with both fixes,
`DeviceCardTagSelection.qml` ranks #1 and `idevice.cpp` is not in the top 3
(tighten `assert files[0] != "src/device/idevice.cpp"` to
`assert files[0] == qml`).

## Verification

Run `tests/test_localize.py` in full (existing + 2 new tests) plus the
full suite once — this touches shared fusion code (`_fuse`, `_score_norms`)
used by every localize path, not just the QML repro.

## Scope note

In scope: `src/axon/tools/localize.py`, `tests/test_localize.py`. No provider
or index-schema changes. Out of scope: raising `RepoIndex`'s default parser
to multi-language (separate, larger change with its own tradeoffs — this
plan works around it instead of fixing indexing itself).
