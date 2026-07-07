"""Deterministic bug localization ranking."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from axon.bm25 import tokenize
from axon.index import RepoIndex
from axon.providers.base import ContextProvider

_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_QUOTE_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"")
_PATH_RE = re.compile(r"\S+\.py")
_EXC_RE = re.compile(r"\b\w+(?:Error|Exception)\b")
_FRAME_RE = re.compile(r'File "([^"]+\.py)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)')
_WEIGHTS = {"traceback": 3.0, "symbol": 1.5, "bm25": 1.0, "graph": 0.7, "spectrum": 2.0}
_RRF_K = 60


@dataclass
class _Candidate:
    file: str
    line: int
    score: float
    evidence: list[str] = field(default_factory=list)
    count: int = 0


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
        ("symbol", _symbol_candidates(index, signals["identifiers"])),
        ("bm25", _bm25_candidates(provider, bug_text, max(k * 3, 10))),
        ("graph", _graph_candidates(provider, signals["identifiers"])),
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
    exceptions = _EXC_RE.findall(text)
    frames = [
        {"file": file, "line": int(line), "name": name}
        for file, line, name in _FRAME_RE.findall(text)
    ]
    return {
        "identifiers": identifiers,
        "quoted_strings": quoted,
        "file_paths": paths,
        "exceptions": exceptions,
        "tracebacks": frames,
    }


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
    for ident in identifiers:
        for symbol in index.find_symbol(ident):
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
    return out


def _bm25_candidates(provider: ContextProvider, bug_text: str, k: int) -> list[dict]:
    out: list[dict] = []
    for rank, hit in enumerate(provider.search(bug_text, k), 1):
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
        for file in ctx.blast_radius:
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
    member_counts: defaultdict[str, int] = defaultdict(int)
    for source, candidates in ranked_lists:
        weight = _WEIGHTS[source]
        for rank, cand in enumerate(candidates, 1):
            file = cand["file"]
            if not file:
                continue
            score = weight / (_RRF_K + rank)
            current = by_file.get(file)
            if current is None:
                current = _Candidate(file=file, line=int(cand.get("line", 1)), score=score)
                by_file[file] = current
            elif score > current.score:
                current.score = score
                current.line = int(cand.get("line", 1))
            current.evidence.append(cand["evidence"])
            member_counts[file] += 1
    for file, count in member_counts.items():
        by_file[file].count = count
    suspects = sorted(
        by_file.values(),
        key=lambda cand: cand.score + 0.1 * cand.count,
        reverse=True,
    )
    return [
        {
            "file": cand.file,
            "line": cand.line,
            "score": round(cand.score + 0.1 * cand.count, 6),
            "evidence": cand.evidence,
        }
        for cand in suspects[:k]
    ]
