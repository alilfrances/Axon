# Phase 4 Spec — security pillar: `sast_scan`, `refute`

Same honesty rule: Axon = deterministic scan + adversarial evidence gathering;
calling agent adjudicates final verdicts. NO exploit execution anywhere —
refute is static-only in v0 (PoC execution deliberately unimplemented; the
tool schema reserves `mode` param accepting only "static" for now).

## src/axon/rules/axon_python.yml

Bundled Semgrep ruleset (works OFFLINE — no registry fetch) covering the
frozen CWE slice (eval/EVAL.md): CWE-78 subprocess/os.system with
shell=True or string concat; CWE-89 cursor.execute with f-string/%/+ concat;
CWE-79 flask/django mark_safe / render_template_string with concat;
CWE-22 open()/Path with user-joined path (basic taint pattern);
CWE-502 pickle.loads/yaml.load w/o SafeLoader; CWE-327 hashlib.md5/sha1 for
password context + DES/ECB; CWE-798 hardcoded password/api_key/secret assign.
~10–14 rules, each: id axon.py.<cwe>.<slug>, message, severity, metadata.cwe.
Include as package data (pyproject: [tool.setuptools.package-data] axon =
["rules/*.yml"] — this is the ONE allowed pyproject edit).

## src/axon/tools/sast.py

`sast_scan(repo: str, config: str | None = None, timeout: int = 600) -> dict`
- Engine resolution: `semgrep` on PATH else `.venv/bin/semgrep` next to
  sys.executable (same venv) else return {error: "semgrep unavailable",
  findings: []} — never crash.
- config default = bundled rules path (importlib.resources); allow override
  (user may pass registry config; that's their network choice).
- Run `semgrep scan --json --config <cfg> --metrics=off` in repo, parse JSON →
  findings: [{id, cwe, path, line, end_line, message, severity, snippet,
  fingerprint (sha1 of id+path+line+snippet)}]. Exclude .axon/, tests/axon_repro/.
- Returns {findings, engine: "semgrep <version>", config_used, stats:{files_scanned?, rules?}}.

## src/axon/tools/refute.py

`refute(repo: str, finding: dict, provider=None, index=None) -> dict`
Static adversarial pass over ONE finding (agent calls per candidate). Checks,
each emitting evidence {check, verdict: supports|challenges|neutral, detail}:
1. **test-context**: path under tests/, conftest, examples/, docs/ →
   challenges ("finding in non-production code").
2. **sanitization-nearby**: window ±10 lines: shlex.quote, parameterized
   execute(sql, params) second arg, re.escape, int()/isdigit coercion of the
   tainted name, os.path.basename, werkzeug secure_filename, html.escape,
   SafeLoader → challenges with the matched line.
3. **constant-input**: taint expression uses only string literals/constants
   defined in-file (no function params/request/os.environ/input()) →
   challenges ("no user-controlled data flows in").
4. **reachability**: index.callers_of(enclosing function) empty AND not a
   route/main/cli entry (decorator heuristics: @app.route, @click, __main__)
   → challenges ("no callers found — possibly dead code"); callers exist →
   supports, list up to 3.
5. **suppression**: `# nosec` / `# nosemgrep` on the line → challenges.
Verdict aggregation: any hard challenge (1,3,5) → "refuted-candidate";
only soft (2,4) → "weakened"; none → "stands". NEVER auto-delete: return
{finding_fingerprint, verdict, evidence:[...], note: "agent adjudicates"}.

## src/axon/tools/triage.py

`triage(repo: str, config=None) -> dict` — convenience pipeline:
sast_scan → refute each finding → {reported: [findings with verdict!=
"refuted-candidate" + attached evidence], suppressed: [refuted ones],
counts: {raw, reported, suppressed}}. This is the precision lever: suppressed
FPs never reach the agent's report unless it asks for them.

## Server tools
Register sast_scan, refute, triage in server.py.

## Tests — tests/test_sast.py, test_refute.py, test_triage.py
New fixture `vuln_repo` in conftest: small flask-ish app with PLANTED:
- true positives: subprocess.run(cmd, shell=True) on request-derived string
  (CWE-78); cursor.execute(f"...{user}") (CWE-89); pickle.loads(blob) (CWE-502);
  hardcoded API_KEY (CWE-798).
- planted FPs: identical subprocess pattern inside tests/test_app.py
  (test-context); execute(f-string) built ONLY from literal constant
  (constant-input); shell=True but arg passed through shlex.quote
  (sanitization).
- sast tests: semgrep available → findings include ≥3 distinct CWEs on right
  files/lines; semgrep missing (monkeypath PATH+resolution) → graceful error
  dict. Mark real-semgrep tests with skipif when binary truly absent.
- refute tests: each planted FP gets its designed challenge + expected verdict;
  true positives → "stands" or "weakened", never "refuted-candidate".
- triage test: precision on fixture = reported TPs / all reported ≥ threshold;
  ALL planted FPs in suppressed; NO true positive suppressed (recall guard).
Semgrep runs are the slow part (~2-5s each): share one sast_scan result via
module-scoped fixture; suite stays < 60s total.
