"""Deterministic bug localization ranking."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field

from axon.bm25 import tokenize
from axon.index import RepoIndex
from axon.providers.base import ContextProvider

_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_QUOTE_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"")
_PATH_RE = re.compile(r"\S+\.py")
_DOTTED_RE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
_FENCED_CODE_RE = re.compile(r"```(?:[^\n`]*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_EXC_RE = re.compile(r"\b\w+(?:Error|Exception)\b")
_FRAME_RE = re.compile(r'File "([^"]+\.py)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)')
_WEIGHTS = {
    "traceback": 3.0,
    "path": 2.5,
    "filename": 2.0,
    "spectrum": 2.0,
    "symbol": 1.5,
    "ident_search": 1.4,
    "search": 1.2,
    "bm25": 1.0,
    "graph": 0.7,
    "recency": 0.5,
}
_RRF_K = 60
_RRF_SCORE_ALPHA = 0.3
_BM25_LOW_SCORE_THRESHOLD = 0.05
_BM25_STRONG_SCORE_THRESHOLD = 0.5
_BM25_STRONG_NORM_THRESHOLD = 0.6
_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "did", "do",
    "does", "doing", "down", "during", "each", "error", "few", "file", "for", "from",
    "further", "had", "has", "have", "having", "here", "how", "if", "in", "into",
    "is", "it", "its", "line", "may", "more", "most", "must", "no", "nor", "not",
    "of", "off", "on", "once", "only", "or", "other", "our", "out", "over", "own",
    "same", "should", "so", "some", "such", "than", "that", "the", "their", "then",
    "there", "these", "this", "those", "through", "to", "too", "under", "until",
    "up", "using", "value", "very", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "why", "will", "with", "would", "you", "your",
}


@dataclass
class _Candidate:
    file: str
    line: int
    score: float
    evidence: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    line_weight: float = 0.0
    line_rank: int = 0
    max_score_norm: float = 0.0
    max_raw_score: float = 0.0
    bm25_pool_size: int = 0


def localize(
    provider: ContextProvider,
    index: RepoIndex,
    bug_text: str,
    k: int = 10,
    failing_test: str | None = None,
) -> dict:
    signals = _extract_signals(bug_text)
    weights = dict(_WEIGHTS)
    lexical_weight_reduced = not signals["strong_identifiers"]
    if lexical_weight_reduced:
        weights["bm25"] *= 0.5
        weights["search"] *= 0.5
    ranked_lists = [
        ("traceback", _traceback_candidates(signals["tracebacks"])),
        ("path", _path_candidates(index, signals)),
        ("filename", _filename_candidates(index, signals["strong_identifiers"])),
        ("symbol", _symbol_candidates(index, signals["strong_identifiers"])),
        ("search", _search_candidates(provider, bug_text, max(k * 3, 10))),
        ("ident_search", _identifier_search_candidates(provider, signals["strong_identifiers"], max(k * 3, 10))),
        ("bm25", _bm25_candidates(provider, bug_text, signals, max(k * 3, 10))),
        ("graph", _graph_candidates(provider, signals["strong_identifiers"])),
        ("recency", _recency_candidates(str(index.repo_root))),
    ]
    spectrum_note = None
    if failing_test:
        spectrum_items, spectrum_note = _spectrum_candidates(str(index.repo_root), failing_test, max(k * 3, 10))
        if spectrum_items:
            ranked_lists.append(("spectrum", spectrum_items))
    suspects = _fuse(ranked_lists, k, weights=weights)
    _attach_functions(index, ranked_lists, suspects, weights=weights)
    note = "deterministic ranking; agent should rerank with reasoning"
    if lexical_weight_reduced:
        note = f"{note}; bug text has no code identifiers; lexical ranking weight reduced"
    if spectrum_note:
        note = f"{note}; {spectrum_note}"
    low_confidence = bool(suspects and suspects[0].get("confidence") == "low")
    if low_confidence:
        note = f"{note}; top suspect low-confidence (single-signal)"
    return {
        "suspects": suspects,
        "k": k,
        "signals": signals,
        "failing_test": failing_test,
        "low_confidence": low_confidence,
        "note": note,
    }


def _extract_signals(text: str) -> dict:
    originals = _IDENT_RE.findall(text)
    identifiers: list[str] = []
    seen: set[str] = set()
    for item in [*originals, *tokenize(" ".join(originals))]:
        if item and item not in seen:
            identifiers.append(item)
            seen.add(item)
    quoted = [a or b for a, b in _QUOTE_RE.findall(text)]
    paths = [match.strip('",') for match in _PATH_RE.findall(text)]
    fenced_spans = [match.strip() for match in _FENCED_CODE_RE.findall(text)]
    text_without_fences = _FENCED_CODE_RE.sub(" ", text)
    inline_spans = [match.strip() for match in _INLINE_CODE_RE.findall(text_without_fences)]
    code_spans = [span for span in [*fenced_spans, *inline_spans] if span]
    dotted_paths = _dedupe(
        match
        for match in _DOTTED_RE.findall(text)
        if "/" not in match and "\\" not in match and not match.endswith(".py")
    )
    exceptions = _EXC_RE.findall(text)
    frames = [
        {"file": file, "line": int(line), "name": name}
        for file, line, name in _FRAME_RE.findall(text)
    ]
    return {
        "identifiers": identifiers,
        "quoted_strings": quoted,
        "file_paths": paths,
        "code_spans": code_spans,
        "dotted_paths": dotted_paths,
        "strong_identifiers": _strong_identifiers(originals, quoted, code_spans, dotted_paths),
        "exceptions": exceptions,
        "tracebacks": frames,
    }


def _dedupe(items) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _strong_identifiers(
    originals: list[str],
    quoted: list[str],
    code_spans: list[str],
    dotted_paths: list[str],
) -> list[str]:
    code_idents = {ident for span in code_spans for ident in _IDENT_RE.findall(span)}
    dotted_segments = {segment for path in dotted_paths for segment in path.split(".")}
    quoted_idents = {item for item in quoted if re.match(r"^[A-Za-z_]\w*$", item)}
    strong: list[str] = []
    seen: set[str] = set()
    for ident in [*originals, *code_idents, *dotted_segments, *quoted_idents]:
        if ident in seen or ident.lower() in _STOPWORDS:
            continue
        if (
            ident in code_idents
            or ident in dotted_segments
            or ident in quoted_idents
            or "_" in ident
            or _is_camel_case(ident)
        ):
            strong.append(ident)
            seen.add(ident)
    return strong


def _is_camel_case(identifier: str) -> bool:
    return (
        any(char.islower() for char in identifier)
        and any(char.isupper() for char in identifier)
        and re.search(r"[a-z][A-Z]", identifier) is not None
    )


def _traceback_candidates(frames: list[dict]) -> list[dict]:
    # Later frames are closer to the thrown exception, so rank them first.
    out: list[dict] = []
    total = len(frames)
    for pos, frame in enumerate(reversed(frames), 1):
        original = total - pos + 1
        out.append(
            {
                "file": frame["file"],
                "line": frame["line"],
                "evidence": f"traceback frame #{original} in {frame['name']}",
            }
        )
    return out


def _symbol_candidates(index: RepoIndex, identifiers: list[str]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    matches_by_ident = [(ident, index.find_symbol(ident)) for ident in identifiers]
    matches_by_ident = [(ident, matches) for ident, matches in matches_by_ident if len(matches) <= 50]
    matches_by_ident.sort(key=lambda item: (len(item[1]), item[0]))
    for ident, matches in matches_by_ident:
        per_identifier = 0
        for symbol in matches:
            key = (symbol.file, symbol.line, ident)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "file": symbol.file,
                    "line": symbol.line,
                    "evidence": f"defines {symbol.name} (symbol match)",
                }
            )
            per_identifier += 1
            if per_identifier >= 5 or len(out) >= 40:
                break
        if len(out) >= 40:
            break
    return out


def _path_candidates(index: RepoIndex, signals: dict) -> list[dict]:
    files = sorted(row[0] for row in index.conn.execute("SELECT path FROM files").fetchall())
    out: list[dict] = []
    seen: set[str] = set()

    def add(file: str, evidence: str) -> None:
        if file not in seen:
            out.append({"file": file, "line": 1, "evidence": evidence})
            seen.add(file)

    for dotted in signals["dotted_paths"]:
        parts = dotted.split(".")
        for start in range(len(parts)):
            suffix = "/".join(parts[start:])
            py_suffix = f"{suffix}.py"
            init_suffix = f"{suffix}/__init__.py"
            for file in files:
                if file.endswith(py_suffix) or file.endswith(init_suffix):
                    add(file, f"path suffix match for {dotted}")

    for path in reversed(signals["file_paths"]):
        normalized = path.removeprefix("./")
        for file in files:
            if file.endswith(normalized):
                add(file, f"path suffix match for {normalized}")

    component_sets: dict[str, set[str]] = {file: _path_components(file) for file in files}
    dfs = Counter(component for components in component_sets.values() for component in components)
    strong_terms = {ident.lower() for ident in signals["strong_identifiers"]}
    scored: list[tuple[float, str, list[str]]] = []
    for file, components in component_sets.items():
        matches = sorted(strong_terms & components)
        score = sum(1 / dfs[component] for component in matches)
        if score > 0:
            scored.append((score, file, matches))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for _, file, matches in scored[:15]:
        add(file, f"path components match: {', '.join(matches)}")
    return out


def _path_components(path: str) -> set[str]:
    stem = path.removesuffix(".py")
    return {part.lower() for part in re.split(r"[/_.]+", stem) if part}


def _filename_candidates(index: RepoIndex, identifiers: list[str]) -> list[dict]:
    strong_terms = {ident.lower() for ident in identifiers}
    if not strong_terms:
        return []
    out: list[dict] = []
    for (file,) in index.conn.execute("SELECT path FROM files ORDER BY path").fetchall():
        if _basename_stem(file).lower() in strong_terms:
            out.append({"file": file, "line": 1, "evidence": "identifier matches filename"})
    return out


def _basename_stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _search_candidates(provider: ContextProvider, bug_text: str, k: int) -> list[dict]:
    # Plain query, same as the standalone `search` tool — bm25's term-stuffed
    # query below can rank differently, so this seeds the fusion with the
    # ranking a user would see from `search` directly.
    out: list[dict] = []
    for rank, hit in enumerate(provider.search(bug_text, k), 1):
        out.append(
            {
                "file": hit.file,
                "line": hit.line,
                "evidence": f"search rank {rank}",
                "raw_score": float(hit.score),
            }
        )
    return out


def _identifier_search_candidates(provider: ContextProvider, identifiers: list[str], k: int) -> list[dict]:
    if not identifiers:
        return []
    query = " ".join(identifiers)
    out: list[dict] = []
    for rank, hit in enumerate(provider.search(query, k), 1):
        out.append(
            {
                "file": hit.file,
                "line": hit.line,
                "evidence": f"identifier search rank {rank}",
                "raw_score": float(hit.score),
            }
        )
    return out


def _bm25_candidates(provider: ContextProvider, bug_text: str, signals: dict, k: int) -> list[dict]:
    terms = [
        *(signals["strong_identifiers"] * 3),
        *(signals["quoted_strings"] * 2),
        *(signals["dotted_paths"] * 2),
        bug_text,
    ]
    query = " ".join(terms)
    out: list[dict] = []
    for rank, hit in enumerate(provider.search(query, k), 1):
        out.append(
            {
                "file": hit.file,
                "line": hit.line,
                "evidence": f"bm25 rank {rank}",
                "raw_score": float(hit.score),
            }
        )
    return out


def _graph_candidates(provider: ContextProvider, identifiers: list[str]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    for ident in identifiers:
        ctx = provider.graph_context(ident)
        if len(ctx.definitions) > 10:
            continue
        for definition in ctx.definitions:
            key = (definition["file"], int(definition.get("line", 1)), f"def:{ident}")
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "file": definition["file"],
                        "line": int(definition.get("line", 1)),
                        "evidence": f"defines {definition.get('name', ident)} (graph)",
                    }
                )
        for caller in ctx.callers:
            cfile = caller.get("file") if isinstance(caller, dict) else caller
            if not cfile:
                continue
            cline = int(caller.get("line", 1)) if isinstance(caller, dict) else 1
            key = (cfile, 1, f"caller:{ident}")
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "file": cfile,
                        "line": cline,
                        "evidence": f"calls {ident} (graph)",
                    }
                )
        for file in ctx.blast_radius[:10]:
            key = (file, 1, f"blast:{ident}")
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "file": file,
                        "line": 1,
                        "evidence": f"blast radius for {ident} (graph)",
                    }
                )
    return out


def _spectrum_candidates(repo: str, failing_test: str, k: int) -> tuple[list[dict], str | None]:
    try:
        from axon.tools.spectrum import spectrum_localize

        result = spectrum_localize(repo, [failing_test], top=k)
    except Exception as exc:
        return [], f"spectrum unavailable ({type(exc).__name__})"
    if result.get("degraded"):
        return [], result.get("note", "spectrum unavailable")
    return [
        {
            "file": item["file"],
            "line": int(item.get("line", 1)),
            "evidence": "spectrum ochiai",
        }
        for item in result.get("suspects", [])
    ], result.get("note")


def _recency_candidates(repo_root: str, limit: int = 20) -> list[dict]:
    try:
        proc = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", "-n", "50"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for name in proc.stdout.splitlines():
        name = name.strip()
        if not name.endswith(".py") or name in seen:
            continue
        seen.add(name)
        out.append({"file": name, "line": 1, "evidence": "recently changed (git log)"})
        if len(out) >= limit:
            break
    return out


def _attach_functions(
    index: RepoIndex,
    ranked_lists: list[tuple[str, list[dict]]],
    suspects: list[dict],
    weights: dict[str, float] | None = None,
) -> None:
    weights = weights or _WEIGHTS
    suspect_files = {s["file"] for s in suspects}
    hits: dict[str, list[tuple[int, float]]] = {}
    for source, candidates in ranked_lists:
        weight = weights[source]
        for cand in candidates:
            file = cand.get("file")
            line = int(cand.get("line", 1) or 1)
            if file in suspect_files and line > 1:
                hits.setdefault(file, []).append((line, weight))
    for suspect in suspects:
        scored: dict[str, dict] = {}
        for line, weight in hits.get(suspect["file"], []):
            row = index.conn.execute(
                "SELECT qualname, line, end_line FROM symbols"
                " WHERE file=? AND kind IN ('function','method') AND line<=? AND end_line>=?"
                " ORDER BY line DESC LIMIT 1",
                (suspect["file"], line, line),
            ).fetchone()
            if row is None:
                continue
            qualname, fn_line, fn_end = row
            entry = scored.setdefault(
                qualname,
                {"qualname": qualname, "line": fn_line, "end_line": fn_end, "score": 0.0},
            )
            entry["score"] += weight
        functions = sorted(scored.values(), key=lambda f: (-f["score"], f["qualname"]))[:3]
        for fn in functions:
            fn["score"] = round(fn["score"], 3)
        suspect["functions"] = functions


def _fuse(
    ranked_lists: list[tuple[str, list[dict]]],
    k: int,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    weights = weights or _WEIGHTS
    by_file: dict[str, _Candidate] = {}
    for source, candidates in ranked_lists:
        weight = weights[source]
        best_by_file: dict[str, tuple[int, dict]] = {}
        for rank, cand in enumerate(candidates, 1):
            file = cand["file"]
            if not file:
                continue
            if file not in best_by_file:
                best_by_file[file] = (rank, cand)
        score_norms = _score_norms([cand for _, cand in best_by_file.values()])
        for file, (rank, cand) in best_by_file.items():
            score_norm = score_norms.get(id(cand), 1.0)
            # Blend retrieval magnitude with RRF rank so near-zero hits cannot tie strong hits at the same rank.
            score = weight * (_RRF_SCORE_ALPHA + (1 - _RRF_SCORE_ALPHA) * score_norm) / (_RRF_K + rank)
            current = by_file.get(file)
            if current is None:
                current = _Candidate(
                    file=file,
                    line=int(cand.get("line", 1)),
                    score=0.0,
                    line_weight=weight,
                    line_rank=rank,
                )
                by_file[file] = current
            current.score += score
            current.max_score_norm = max(current.max_score_norm, score_norm)
            current.max_raw_score = max(current.max_raw_score, float(cand.get("raw_score", 0.0) or 0.0))
            if weight > current.line_weight or (weight == current.line_weight and rank < current.line_rank):
                current.line = int(cand.get("line", 1))
                current.line_weight = weight
                current.line_rank = rank
            current.sources.add(source)
            if source == "bm25":
                current.bm25_pool_size = len(best_by_file)
            if len(current.evidence) < 8:
                current.evidence.append(cand["evidence"])
    suspects = sorted(
        by_file.values(),
        key=_fuse_sort_key,
    )
    return [
        {
            "file": cand.file,
            "line": cand.line,
            "score": round(cand.score, 6),
            "evidence": cand.evidence,
            "confidence": _confidence(cand.sources, cand.max_score_norm, cand.max_raw_score, cand.bm25_pool_size),
        }
        for cand in suspects[:k]
    ]


def _score_norms(candidates: list[dict]) -> dict[int, float]:
    scored = [(id(cand), float(cand.get("raw_score", 0.0) or 0.0)) for cand in candidates if "raw_score" in cand]
    if not scored:
        return {}
    values = [score for _, score in scored]
    lo = min(values)
    hi = max(values)
    if hi > lo:
        median = _median(values)
        if median > 0 and hi > 5 * median:
            hi = max(lo, median * 3)
            lo = min(lo, 0.0)
        return {cand_id: max(0.0, min(1.0, (score - lo) / (hi - lo))) for cand_id, score in scored}
    norm = 1.0 if hi >= _BM25_LOW_SCORE_THRESHOLD else 0.0
    return {cand_id: norm for cand_id, _ in scored}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


_LEXICAL_SOURCES = {"bm25", "ident_search", "search"}


def _confidence(
    sources: set[str], max_score_norm: float = 0.0, max_raw_score: float = 0.0, bm25_pool_size: int = 0
) -> str:
    # bm25 and search both draw from the same underlying retrieval call, so
    # agreeing on both is not independent confirmation — treat them as one
    # signal family for confidence purposes.
    if sources and sources <= _LEXICAL_SOURCES:
        if max_raw_score < _BM25_LOW_SCORE_THRESHOLD:
            return "low"
        # A pool of 1 means score_norm was assigned by the singleton fallback
        # (1.0 whenever the lone hit clears the low-score floor), not by
        # standing out among real peers — that can't earn "medium".
        if (
            bm25_pool_size > 1
            and max_raw_score >= _BM25_STRONG_SCORE_THRESHOLD
            and max_score_norm >= _BM25_STRONG_NORM_THRESHOLD
        ):
            return "medium"
        return "low"
    if len(sources) == 1:
        return "low"
    if len(sources) == 2:
        return "medium"
    return "high"


def _confidence_tier(cand: _Candidate) -> int:
    return {"low": 0, "medium": 1, "high": 2}[
        _confidence(cand.sources, cand.max_score_norm, cand.max_raw_score, cand.bm25_pool_size)
    ]


def _fuse_sort_key(cand: _Candidate) -> tuple:
    tier = _confidence_tier(cand)
    if tier == 2:
        return (-tier, -cand.line_weight, cand.line_rank, -cand.score, cand.file)
    return (-tier, -cand.score, cand.file)
