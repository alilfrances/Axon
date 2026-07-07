"""Deterministic bug localization ranking."""

from __future__ import annotations

import re
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
_WEIGHTS = {"traceback": 3.0, "path": 2.5, "spectrum": 2.0, "symbol": 1.5, "bm25": 1.0, "graph": 0.7}
_RRF_K = 60
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
    line_weight: float = 0.0
    line_rank: int = 0


def localize(
    provider: ContextProvider,
    index: RepoIndex,
    bug_text: str,
    k: int = 10,
    failing_test: str | None = None,
) -> dict:
    signals = _extract_signals(bug_text)
    ranked_lists = [
        ("traceback", _traceback_candidates(signals["tracebacks"])),
        ("path", _path_candidates(index, signals)),
        ("symbol", _symbol_candidates(index, signals["strong_identifiers"])),
        ("bm25", _bm25_candidates(provider, bug_text, signals, max(k * 3, 10))),
        ("graph", _graph_candidates(provider, signals["strong_identifiers"])),
    ]
    spectrum_note = None
    if failing_test:
        spectrum_items, spectrum_note = _spectrum_candidates(str(index.repo_root), failing_test, max(k * 3, 10))
        if spectrum_items:
            ranked_lists.append(("spectrum", spectrum_items))
    suspects = _fuse(ranked_lists, k)
    note = "deterministic ranking; agent should rerank with reasoning"
    if spectrum_note:
        note = f"{note}; {spectrum_note}"
    return {
        "suspects": suspects,
        "k": k,
        "signals": signals,
        "failing_test": failing_test,
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
            key = (caller["file"], 1, f"caller:{ident}")
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "file": caller["file"],
                        "line": int(caller.get("line", 1)),
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


def _fuse(ranked_lists: list[tuple[str, list[dict]]], k: int) -> list[dict]:
    by_file: dict[str, _Candidate] = {}
    for source, candidates in ranked_lists:
        weight = _WEIGHTS[source]
        best_by_file: dict[str, tuple[int, dict]] = {}
        for rank, cand in enumerate(candidates, 1):
            file = cand["file"]
            if not file:
                continue
            if file not in best_by_file:
                best_by_file[file] = (rank, cand)
        for file, (rank, cand) in best_by_file.items():
            score = weight / (_RRF_K + rank)
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
            if weight > current.line_weight or (weight == current.line_weight and rank < current.line_rank):
                current.line = int(cand.get("line", 1))
                current.line_weight = weight
                current.line_rank = rank
            if len(current.evidence) < 8:
                current.evidence.append(cand["evidence"])
    suspects = sorted(
        by_file.values(),
        key=lambda cand: (-cand.score, cand.file),
    )
    return [
        {
            "file": cand.file,
            "line": cand.line,
            "score": round(cand.score, 6),
            "evidence": cand.evidence,
        }
        for cand in suspects[:k]
    ]
