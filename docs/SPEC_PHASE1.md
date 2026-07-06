# Phase 1 Implementation Spec (for implementer)

Already written (DO NOT rewrite, build against them): `src/axon/parsing.py`,
`src/axon/index.py`, `pyproject.toml`. Match their style: dataclasses, type
hints, terse docstrings, comments only for non-obvious constraints.

Venv: `.venv/` (mcp + pytest + semgrep installed). Run tests:
`.venv/bin/python -m pytest`. Install package editable first:
`.venv/bin/pip install -e . --no-deps`.

## Modules to create

### src/axon/bm25.py
Pure-Python BM25 (k1=1.5, b=0.75). No deps.
- `tokenize(text: str) -> list[str]` — lowercase; split identifiers on
  non-alnum AND camelCase AND snake_case; keep whole identifier too.
- `class BM25Corpus`: `add(doc_id: str, text: str)`, `finalize()`,
  `search(query: str, k: int = 10) -> list[tuple[str, float]]`.

### src/axon/providers/base.py
- `@dataclass SearchHit`: file, line, snippet, score.
- `@dataclass GraphContext`: symbol, definitions (list[dict]), callers
  (list[dict]), callees (list[str]), blast_radius (list[str]),
  degraded (bool), backend (str).
- `class ContextProvider(ABC)`: `name: str`;
  `index(repo: Path) -> dict`; `graph_context(symbol: str) -> GraphContext`;
  `search(query: str, k: int = 10) -> list[SearchHit]`.

### src/axon/providers/builtin.py
`BuiltinProvider(ContextProvider)` — wraps RepoIndex + BM25Corpus.
- `index()`: RepoIndex.refresh(); build BM25 over per-symbol docs (qualname +
  name tokens + source segment lines[line-1:end_line] capped 80 lines) and
  per-file docs (path + first 100 lines). Doc ids: `sym:<file>:<line>:<qualname>`
  and `file:<path>`.
- `graph_context()`: from RepoIndex (find_symbol/callers_of/callees_of/
  blast_radius). degraded=False, backend="builtin".
- `search()`: BM25 over both corpora; map sym docs to (file, line), file docs
  to (file, 1); snippet = first matching source line region (up to 5 lines).

### src/axon/providers/grep.py
`GrepProvider(ContextProvider)` — floor. Uses `rg --json` if on PATH else
pure-Python line scan over *.py.
- `index()`: no-op stats.
- `graph_context()`: definitions via regex `^\s*(def|class)\s+NAME\b`;
  callers via `\bNAME\s*\(` excluding def lines; callees=[]  blast_radius=[],
  degraded=True, backend="grep".
- `search()`: term-OR regex search, score = match count per file, snippet =
  matched line.

### src/axon/providers/cortex.py
`CortexProvider(ContextProvider)` — adapter over `cortex` CLI.
- `available() -> bool` (staticmethod): `shutil.which("cortex")` AND
  `cortex --help` exits 0 within 5s.
- Methods shell out (`cortex query ...` etc.) with subprocess timeout 30s,
  parse JSON if possible; on ANY failure fall back to internal
  BuiltinProvider instance and set backend="cortex-fallback-builtin".
  Do not guess CLI flags deeply: wrap `cortex_query`-style subcommands
  defensively; this adapter must never crash the server. backend="cortex",
  degraded=False when native.

### src/axon/providers/select.py
- `select_provider(repo: Path, prefer: str | None = None) -> ContextProvider`
  Ladder: prefer arg (exact) else Cortex if available() else Builtin; Grep
  only on explicit prefer="grep" or if Builtin init raises. Log choice via
  `logging.getLogger("axon")`.

### src/axon/sandbox.py
- `@dataclass SandboxResult`: exit_code, stdout, stderr, duration_s, timed_out.
- `run_in_sandbox(cmd: list[str], cwd: Path, timeout: int = 300,
  env_extra: dict | None = None) -> SandboxResult` — subprocess.run, captured
  output (cap each stream at 200_000 chars, note truncation), kills on timeout.
- `ensure_venv(repo: Path) -> Path` — create `.axon/venv` if missing
  (`python -m venv`), `pip install -e repo` best-effort if pyproject/setup
  present, return python path. Idempotent, offline-tolerant (pip failure →
  still return python path).

### src/axon/tools/run_tests.py
- `run_tests(repo: str, test_target: str | None = None, timeout: int = 300)
  -> dict` — uses ensure_venv + run_in_sandbox to run pytest with `-q --tb=line`
  (append test_target if given). Prefer repo's own `.axon/venv`; if pytest
  missing there, fall back to `sys.executable`. Parse output → dict:
  {passed: int, failed: int, errors: int, failures: [{test_id, message}],
  exit_code, timed_out, duration_s, raw_tail (last 2000 chars)}.
  Parse `-q` summary lines robustly (e.g. "2 failed, 3 passed in 0.12s",
  "FAILED test_x.py::test_y - AssertionError: ...").

### src/axon/tools/graph_context.py
- `get_graph_context(provider, symbol) -> dict` and
  `search_code(provider, query, k=10) -> list[dict]` — thin, dataclass→dict.

### src/axon/server.py
FastMCP server (`mcp.server.fastmcp.FastMCP`, name "axon").
Lazy global provider per repo path (dict cache). Tools (all take `repo: str`):
- `axon_index(repo)` — (re)index, returns stats + backend name.
- `graph_context(repo, symbol)`
- `search_code(repo, query, k=10)`
- `run_tests(repo, test_target=None, timeout=300)`
Each returns JSON-serializable dict. `def main(): mcp.run()` (stdio).

### src/axon/cli.py
argparse: `axon serve` (server.main), `axon index <path>`, `axon doctor`
(report python version, rg/cortex/semgrep availability, active backend for
cwd). `main()` entry point.

## Tests (tests/, pytest, fast, no network, no Docker)

conftest.py: `fixture_repo(tmp_path)` factory fixture writing a small package:
`calc/__init__.py`, `calc/core.py` (functions `add`, `divide` — divide has
callers), `calc/api.py` (imports core, calls divide), plus
`tests/test_calc.py` inside fixture repo (one passing, one failing test:
`divide(1, 0)` expecting ZeroDivisionError handling bug).

- test_parsing.py: symbols found (function/class/method), calls recorded,
  imports recorded, syntax-error file → parse_error set, no crash.
- test_index.py: refresh stats; incremental (2nd refresh parsed==0; touch file
  → parsed==1; delete file → removed==1); find_symbol; callers_of; blast_radius
  includes api.py for divide.
- test_bm25.py: exact-token doc ranks first; camelCase/snake splitting; empty
  query → [].
- test_providers.py: Builtin graph_context on fixture (definitions non-empty,
  callers include api.py, degraded False); search finds divide's file in top-3;
  Grep degraded=True, blast_radius==[]; select_provider(prefer="builtin")
  returns builtin; select_provider default never raises (monkeypatch
  CortexProvider.available → False → builtin chosen).
- test_sandbox.py: run true/false exit codes; timeout kills (sleep 5,
  timeout=1, timed_out True, duration < 3).
- test_run_tests.py: on fixture repo, run_tests reports the planted failing
  test (failed>=1, its test_id captured) using sys.executable fallback path
  (skip ensure_venv in test via monkeypatch or param to keep test fast).
- test_server.py: import server module, assert tools registered (FastMCP
  list_tools or internal registry), call underlying functions directly on
  fixture repo — do NOT spawn stdio client.

## Constraints
- No new runtime deps. stdlib + mcp + semgrep only. pytest dev-only.
- Every test < 2s except sandbox timeout test (~1.5s). Whole suite < 30s.
- No network, no Docker, no global state leaks (.axon inside tmp fixture only).
- All code must run on macOS + Linux. Windows: best-effort, don't use
  POSIX-only APIs where avoidable.
