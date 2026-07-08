"""Builtin context provider using RepoIndex and BM25."""

from __future__ import annotations

from pathlib import Path

from axon.bm25 import BM25Corpus
from axon.index import RepoIndex
from axon.parsing import TEXT_EXTENSIONS, iter_source_files

from .base import GraphContext, SearchHit, dedupe_hits


class BuiltinProvider:
    backend = "builtin"

    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()
        self.indexer = RepoIndex(self.repo)
        self.corpus = BM25Corpus()
        self._doc_meta: dict[str, tuple[str, int]] = {}
        self.index(self.repo)

    def index(self, repo: Path) -> dict:
        if Path(repo).resolve() != self.repo:
            self.close()
            self.repo = Path(repo).resolve()
            self.indexer = RepoIndex(self.repo)
        stats = self.indexer.refresh()
        self._rebuild_corpus()
        stats["python_files"] = stats["files"]
        stats["text_files"] = self.text_file_count()
        if stats["text_files"] != stats["python_files"]:
            stats["note"] = self.fallback_note()
        return stats

    def close(self) -> None:
        self.indexer.close()

    def graph_context(self, symbol: str) -> GraphContext:
        definitions = [
            {
                "name": s.name,
                "qualname": s.qualname,
                "kind": s.kind,
                "file": s.file,
                "line": s.line,
                "end_line": s.end_line,
            }
            for s in self.indexer.find_symbol(symbol)
        ]
        callees: set[str] = set()
        for definition in definitions:
            callees.update(self.indexer.callees_of(definition["qualname"]))
        return GraphContext(
            symbol=symbol,
            definitions=definitions,
            callers=self.indexer.callers_of(symbol),
            callees=sorted(callees),
            blast_radius=self.indexer.blast_radius(symbol),
            degraded=False,
            backend=self.backend,
            note=self._scope_note(bool(definitions)),
        )

    def _scope_note(self, found: bool) -> str:
        """Explain an empty result so callers can tell 'not found' from
        'unsupported' — the builtin index only understands Python."""
        if found:
            return ""
        files = self.indexer.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return (
            f"symbol not found in {files} indexed Python file(s); "
            "builtin analysis is Python-only, so symbols defined in other "
            "languages are not represented"
        )

    def fallback_note(self) -> str:
        return (
            f"builtin fallback: full-text search across {self.text_file_count()} files; "
            "symbol graph is Python-only"
        )

    def text_file_count(self) -> int:
        return len(iter_source_files(self.repo, TEXT_EXTENSIONS))

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        raw: list[SearchHit] = []
        for hit in self.corpus.search(query, max(k * 3, k)):
            file, line = self._doc_meta.get(hit.doc_id, ("", 1))
            raw.append(
                SearchHit(
                    file=file,
                    line=line,
                    score=hit.score,
                    snippet=self._snippet(file, line, query),
                    backend=self.backend,
                )
            )
        return dedupe_hits(raw, k)

    def _rebuild_corpus(self) -> None:
        docs: dict[str, str] = {}
        self._doc_meta.clear()
        rows = self.indexer.conn.execute(
            "SELECT name, qualname, kind, file, line, end_line FROM symbols"
        ).fetchall()
        for name, qualname, kind, file, line, end_line in rows:
            path = self.repo / file
            lines = self._read_lines(path)
            segment = "\n".join(lines[max(0, line - 1): min(len(lines), end_line, line + 79)])
            doc_id = f"sym:{file}:{line}:{qualname}"
            docs[doc_id] = f"{file}\n{name}\n{qualname}\n{kind}\n{segment}"
            self._doc_meta[doc_id] = (file, line)
        for path in iter_source_files(self.repo, TEXT_EXTENSIONS):
            file = str(path.relative_to(self.repo))
            lines = self._read_lines(path)
            for chunk_no, start in enumerate(range(0, max(len(lines), 1), 100), 1):
                doc_id = f"file:{file}:{chunk_no}"
                docs[doc_id] = f"{file}\n" + "\n".join(lines[start:start + 100])
                self._doc_meta[doc_id] = (file, start + 1)
        self.corpus.build(docs)

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def _snippet(self, file: str, line: int, query: str) -> str:
        lines = self._read_lines(self.repo / file)
        if not lines:
            return ""
        terms = {term.lower() for term in query.replace("_", " ").split() if term}
        start = max(0, line - 1)
        for idx, text in enumerate(lines):
            lowered = text.lower()
            if any(term in lowered for term in terms):
                start = max(0, idx - 2)
                break
        return "\n".join(lines[start:start + 5])
