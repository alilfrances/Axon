# Localize/Investigate Fusion — Open Questions & Fix Plan

Date: 2026-07-09 · Scope: `src/axon/tools/localize.py` fusion value, lexical
query quality, large-file bias, and QML graph def-resolution. Follows the
confidence-inflation + search-seeding fix in commit `3cf528a`.

## Context

QA raised three open questions after that fix landed:

1. What does localize's fusion add over just using `search`'s ranking?
2. Is feeding raw NL bug text straight into lexical search the core defect?
3. Is there a large-file ("god file") bias, and should ranking normalize/
   down-weight by length independent of query? What's the trade-off?
4. (Carried over) QML `defines X (graph)` edges resolve to a usage site
   instead of the component's own file — provider bug or fusion mislabel?

Each is investigated below with a verdict and a proposed fix.

---

## Q1 — What does fusion add over plain `search`?

**Verdict: real value when other signals fire, marginal-to-negative when
they don't.** `ranked_lists` in `localize()` combines traceback frames, path
suffix/component matches, symbol-table lookups, the new `search` signal,
raw BM25, graph blast-radius, git recency, and (when a failing test is
given) spectrum/Ochiai fault localization — sources a single `search` call
has no access to (exact traceback frame, structural callers, test-failure
correlation). That corroboration is the actual value-add, and it shows up
in the confidence tiering: multi-source agreement earns "medium"/"high",
which a lone `search` hit can never signal on its own.

The failure mode QA hit (`search` correct at rank 1, `localize` burying it)
was `bug_text` being re-queried through a *different, term-stuffed* string
for BM25 while `search` used the plain string — now fixed by feeding the
plain `bug_text` into its own `search` fusion signal (commit `3cf528a`).
With that in place, fusion should no longer score strictly worse than
`search` alone when no other signal contradicts it; it can only do better
when a traceback/path/symbol/spectrum signal agrees.

**Residual gap:** when *no* structural signal fires (no traceback, no
strong path/dotted-path/identifier overlap, no failing test), fusion
degenerates to `search` + `bm25` (now correctly deduplicated as one
"lexical family") plus possibly noisy `graph`/`recency` entries. In that
regime fusion is not adding corroboration, it's just re-ranking the same
lexical result via RRF, which can reorder within the pack. Low risk given
current tests, but worth a regression test: single-signal lexical-only bug
report should reproduce `search`'s top rank exactly (not just its file
membership).

**Fix:** add `test_localize_lexical_only_matches_plain_search_rank_one`
asserting `suspects[0]["file"] == search(bug_text, k)[0].file` when no
traceback/path/symbol/graph/spectrum signal contributes any candidate.

---

## Q2 — Is raw NL bug text fed to lexical search the core defect?

**Verdict: yes, partially — architecture gap, not a bug in the fusion
code.** `BM25Corpus` (`bm25.py`) is pure lexical (`tf`/`idf` over
tokenized identifiers/words); it has no semantic/embedding fallback. When
Cortex MCP is available, `CortexProvider.search` delegates to
`cortex_query`, which may or may not be doing semantic retrieval
internally (opaque to Axon — Cortex repo's concern). When Cortex is
unavailable and Axon falls back to `BuiltinProvider`, retrieval is 100%
lexical token overlap. A bug report written in prose ("widget flickers
when resizing during drag") has weak token overlap with the code unless
it happens to quote an identifier, error string, or file path verbatim —
which is exactly why `_extract_signals`/`_strong_identifiers` exist (to
pull quoted/coded/dotted identifiers out and weight them 3x into the BM25
query). That mitigation only works when the bug text *contains* such
identifiers; free-form NL descriptions with none get no lift.

**Trade-off:** adding real semantic/embedding search to the builtin
fallback is a meaningfully sized feature (needs an embedding model,
storage, and invalidation on reindex) — out of scope for a quick fix.
Cheaper mitigations that reduce the gap without that cost:

- **Fix:** when `_strong_identifiers` extracts zero terms (pure-prose bug
  report), boost the `bm25`/`search` fusion weight down relative to
  `path`/`symbol`/`spectrum` (currently fixed weights regardless of query
  quality) so a low-signal lexical hit doesn't outrank a weaker-looking
  but more structurally grounded candidate. Concretely: track whether
  `signals["strong_identifiers"]` is empty and, if so, halve `_WEIGHTS`
  for `bm25`/`search` in that call's `ranked_lists` construction (a local
  copy, not the module-level dict).
- **Fix:** surface this in the tool output — when `strong_identifiers` is
  empty, add a note like `"bug text has no code identifiers; lexical
  ranking is low-confidence, consider adding an error message, file name,
  or symbol"` so the calling agent knows to enrich the query rather than
  trust a low-signal top suspect.

Full semantic/embedding fallback is a separate, larger effort — flag as a
follow-up, not part of this plan's implementation scope.

---

## Q3 — Large-file ("god file") bias

**Verdict: real, structural, distinct from the confidence-inflation bug
fixed in `3cf528a`.** `BuiltinProvider._rebuild_corpus` (`builtin.py`)
already chunks per-symbol and in 100-line file segments, so per-chunk BM25
scoring gets standard length normalization (`k1`/`b` in `BM25Corpus`).
But normalization happens *within* a chunk, not *across* a file: a large
file produces many chunks, and each chunk is an independent shot at
matching any query term. More chunks means more entries competing in the
top-`k` pool, so large files are statistically more likely to place
*some* chunk near the top of `bm25`/`search` results even when that
specific chunk isn't causally related to the bug — pure surface-area
effect, not a scoring bug.

**Trade-off:** down-weighting by raw file size is dangerous — genuinely
central, large "core" modules (e.g. a 2000-line dispatcher) are
legitimately implicated in many real bugs and should not be penalized
just for being large. Punishing size directly would hurt recall on
exactly the files most bugs touch.

**Fix — diversity cap, not size penalty:** in `_fuse`, `best_by_file`
already keeps only the single best-ranked candidate per file per source
list (`if file not in best_by_file`), which caps a file to one entry from
`bm25`; but if `search` *and* `bm25` each surface a different chunk of the
same large file, and `symbol`/`path` don't corroborate, the file still
gets two "lexical family" hits — already collapsed into one for
confidence tiering per the `3cf528a` fix, so no double-count there. The
actual residual bias is upstream, inside `BM25Corpus.search`/
`BuiltinProvider.search`: nothing stops one file's chunks from filling
several of the top-`k*3` slots handed to `_bm25_candidates`/
`_search_candidates`, crowding out a smaller, more relevant file that only
gets one chunk considered before the `k*3` cutoff. Add a **per-file cap**
in `BuiltinProvider.search` (e.g. at most 2 chunks per file survive
`dedupe_hits` before truncating to `k`), so a large file's many chunks
don't monopolize the candidate pool at the expense of file diversity.
This is a size-agnostic fix (caps chunk *count*, not score) — it doesn't
penalize a large file's best matching chunk, just stops one file from
occupying multiple ranks that could otherwise surface a different file.

---

## Q4 — QML `defines X` graph edges resolve to usage site (carried over, P3)

**Verdict: Cortex-repo bug, not an Axon fusion mislabel — confirmed by
code read, no fix in this repo.** `CortexProvider._graph_context_via_mcp`
(`providers/cortex.py:247-303`) builds `definitions` directly from
whatever `cortex_search_symbols` returns: `file: n.get("source_ref", "")`,
`line: n.get("span_start") or 1`. Axon does no resolution of its own here
— it trusts Cortex's `source_ref` on the matched node verbatim. If that
node's `source_ref` points at the file where the QML component is *used*
rather than where it's *declared*, the mislabeling happened inside
Cortex's own QML parser/graph builder (in the sibling `Cortex` repo, not
here), before the payload ever reaches Axon.

**Fix (this repo, defensive only):** none justified — Axon has no
independent way to tell definition-node source_ref from usage-node
source_ref; adding a heuristic here (e.g. preferring nodes whose `kind`
looks like a component/class over ones that look like a usage reference)
would be guessing at Cortex's internal node vocabulary and could silently
suppress correct results on repos where Cortex gets it right. **Action:
file a ticket against the Cortex repo** (`~/Personal Projects/Cortex`)
describing the QML component-definition resolution bug with the repro
QA already captured (`DeviceCardTagSelection` definition edge resolving
to `DeviceCardDisplaySection.qml`, the usage site). No Axon code change.

---

## Implementation Scope (for delegation)

In scope, all in `src/axon/tools/localize.py` / `providers/builtin.py` /
`tests/test_localize.py`:

1. **Q1** — add lexical-only regression test comparing `localize`'s top
   suspect against `search`'s rank-1 file when no structural signal
   contributes.
2. **Q2** — when `signals["strong_identifiers"]` is empty, halve the
   effective `bm25`/`search` fusion weights for that call (local dict
   copy, do not mutate module-level `_WEIGHTS`); add a
   `"note"` addendum when this fires. Add tests for both the halved-weight
   ranking effect and the note text.
3. **Q3** — add a per-file chunk cap (2) in `BuiltinProvider.search`
   before/within `dedupe_hits` truncation to `k`, so one large file's
   chunks can't crowd out file diversity in the top-`k*3` candidate pool
   handed to localize. Add a test with one large multi-chunk file and one
   small single-chunk relevant file, asserting the small file still
   surfaces within top-k.

Out of scope: Q4 (Cortex repo), full semantic/embedding search fallback
(flagged as a larger follow-up, not scheduled here).

## Verification

- `pytest tests/test_localize.py tests/test_investigate.py -q` after each
  change; keep all existing assertions green (per `3cf528a`'s tier-sort
  and lexical-family behavior).
- No version bump as part of implementation — bump once at the end of the
  full slice, following existing repo convention (see `3cf528a`,
  `9f4dc0d`).
