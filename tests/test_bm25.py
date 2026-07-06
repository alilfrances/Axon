from __future__ import annotations

from axon.bm25 import BM25Corpus, tokenize


def test_tokenize_handles_identifier_shapes():
    tokens = tokenize("parseHTTPResponse snake_case alpha-beta")

    assert "parsehttpresponse" in tokens
    assert "parse" in tokens
    assert "http" in tokens
    assert "response" in tokens
    assert "snake_case" in tokens
    assert "snake" in tokens
    assert "case" in tokens
    assert "alpha" in tokens
    assert "beta" in tokens


def test_bm25_ranks_relevant_doc_and_empty_query():
    corpus = BM25Corpus({"a": "divide zero handling", "b": "unrelated addition"})

    hits = corpus.search("divide zero")

    assert hits[0].doc_id == "a"
    assert corpus.search("") == []
