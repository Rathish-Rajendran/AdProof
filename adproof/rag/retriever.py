from __future__ import annotations

import re
from collections.abc import Iterable

import numpy as np
from rank_bm25 import BM25Plus

from adproof.rag.chunker import CorpusChunk

TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.casefold())


class HybridRetriever:
    def __init__(
        self,
        chunks: list[CorpusChunk],
        embeddings: np.ndarray,
        embedder,
        *,
        rrf_k: int = 60,
    ):
        self.chunks = chunks
        self.embeddings = np.asarray(embeddings, dtype=np.float32)
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.bm25 = BM25Plus([tokenize(chunk.text) for chunk in chunks])

    def retrieve(self, query: str, *, top_k: int = 6) -> list[CorpusChunk]:
        if not self.chunks:
            return []
        bm25_scores = self.bm25.get_scores(tokenize(query))
        bm25_order = np.argsort(bm25_scores)[::-1]
        query_vector = np.asarray(list(self.embedder.embed([query]))[0], dtype=np.float32)
        norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(query_vector)
        cosine = np.divide(
            self.embeddings @ query_vector,
            norms,
            out=np.zeros(len(self.chunks), dtype=np.float32),
            where=norms != 0,
        )
        vector_order = np.argsort(cosine)[::-1]
        scores: dict[int, float] = {}
        for order in (bm25_order, vector_order):
            for rank, index in enumerate(order, start=1):
                scores[int(index)] = scores.get(int(index), 0.0) + 1 / (self.rrf_k + rank)
        ranked = sorted(scores, key=scores.get, reverse=True)[:top_k]
        return [self.chunks[index] for index in ranked]


def embed_chunks(embedder, chunks: Iterable[CorpusChunk]) -> np.ndarray:
    vectors = list(embedder.embed([chunk.text for chunk in chunks]))
    return np.asarray(vectors, dtype=np.float32)
