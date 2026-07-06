# Phase 2 Spec — `localize`

Honest division of labor: Axon = deterministic evidence + candidate ranking;
the CALLING agent is the LLM that reranks/adjudicates. No LLM calls inside Axon.

## src/axon/tools/localize.py

`localize(provider, index: RepoIndex, bug_text: str, k: int = 10,
failing_test: str | None = None) -> dict`

Pipeline:
1. **Signal extraction** from bug_text: identifiers (regex
   `[A-Za-z_][A-Za-z0-9_]{2,}`, camel/snake split like bm25.tokenize but keep
   originals), quoted strings, file paths (`\S+\.py`), exception names
   (`\w+Error|\w+Exception`), traceback frames if present
   (`File "...", line N, in name` — these are GOLD, weight accordingly).
2. **Candidate generation** (each source tagged):
   - traceback frames → direct file:line candidates (source="traceback")
   - provider.search(bug_text, k=20) (source="bm25")
   - index.find_symbol(ident) for each extracted identifier (source="symbol")
   - graph expansion: callers/callees of symbol hits, 1 hop (source="graph")
3. **Rank fusion**: Reciprocal Rank Fusion (RRF, rrf_k=60) across source lists,
   with source weights: traceback 3.0, symbol 1.5, bm25 1.0, graph 0.7.
   Aggregate to FILE level (max of member scores + 0.1*count bonus), keep best
   line per file.
4. Output:
   {suspects: [{file, line, score, evidence: [str, ...]}], k, signals: {...},
    note: "deterministic ranking; agent should rerank with reasoning"}
   suspects sorted desc, len ≤ k. evidence strings say WHY (e.g.
   "traceback frame #2", "defines divide (symbol match)", "bm25 rank 3",
   "calls divide (graph)").

`failing_test` param: reserved hook, stored in output; spectrum FL lands in
Phase 3 (needs test infra).

## Server tool

`localize(repo, bug_text, k=10, failing_test=None)` registered in server.py,
same lazy provider/index cache.

## Tests — tests/test_localize.py

Extend fixture repo (conftest) with a planted bug scenario:
- bug_text with traceback pointing at calc/core.py divide → core.py is
  suspect #1, evidence mentions traceback.
- bug_text WITHOUT traceback, prose mentioning "divide by zero in divide()"
  → core.py in top-3 (File@3 smoke).
- bug_text mentioning api-only terms → api.py ranked, graph evidence pulls
  core.py into top-k.
- empty bug_text → empty suspects, no crash.
- RRF unit test: item ranked #1 in two lists beats #1 in one list.

Constraints: same as Phase 1 (fast, no network, no new deps).
