"""Tiny pure-Python BM25 retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")


@dataclass(frozen=True)
class BM25Hit:
    doc_id: str
    score: float
    text: str


def tokenize(text: str) -> list[str]:
    """Split on punctuation, snake_case, and camelCase; keep identifiers too."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        token = raw.lower()
        if token:
            out.append(token)
        parts = [p for chunk in raw.split("_") for p in _CAMEL_RE.findall(chunk)]
        out.extend(p.lower() for p in parts if p)
    return out


class BM25Corpus:
    def __init__(self, docs: dict[str, str] | None = None, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: dict[str, str] = {}
        self.term_freqs: dict[str, Counter[str]] = {}
        self.doc_lens: dict[str, int] = {}
        self.doc_freqs: Counter[str] = Counter()
        self.avgdl = 0.0
        if docs:
            self.build(docs)

    def build(self, docs: dict[str, str]) -> None:
        self.docs = dict(docs)
        self.term_freqs.clear()
        self.doc_lens.clear()
        self.doc_freqs.clear()
        for doc_id, text in self.docs.items():
            counts = Counter(tokenize(text))
            self.term_freqs[doc_id] = counts
            self.doc_lens[doc_id] = sum(counts.values())
            self.doc_freqs.update(counts.keys())
        self.avgdl = (
            sum(self.doc_lens.values()) / len(self.doc_lens) if self.doc_lens else 0.0
        )

    def search(self, query: str, k: int = 10) -> list[BM25Hit]:
        terms = tokenize(query)
        if not terms or not self.docs:
            return []
        n_docs = len(self.docs)
        q_terms = Counter(terms)
        hits: list[BM25Hit] = []
        for doc_id, freqs in self.term_freqs.items():
            score = 0.0
            dl = self.doc_lens[doc_id] or 1
            for term, qf in q_terms.items():
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                df = self.doc_freqs.get(term, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                score += qf * idf * (tf * (self.k1 + 1)) / denom
            if score > 0:
                hits.append(BM25Hit(doc_id, score, self.docs[doc_id]))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:k]
