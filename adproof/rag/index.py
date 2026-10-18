from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

import numpy as np

from adproof.rag.chunker import CorpusChunk, CorpusDocument, chunk_document, load_corpus
from adproof.rag.retriever import HybridRetriever, embed_chunks

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "data/corpus/aerobeat"
INDEX_PATH = ROOT / "runtime/corpus_index.sqlite3"
MODEL_NAME = "BAAI/bge-small-en-v1.5"


class FastEmbedder:
    def __init__(self, model_name: str = MODEL_NAME):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model_name)

    def embed(self, texts):
        return self.model.embed(list(texts))


class CorpusIndex:
    def __init__(
        self,
        path: Path = INDEX_PATH,
        corpus_path: Path = CORPUS_PATH,
        embedder=None,
    ):
        self.path = path
        self.corpus_path = corpus_path
        self.embedder = embedder
        self._runtime_embedder = None

    def _get_embedder(self):
        if self.embedder is not None:
            return self.embedder
        if self._runtime_embedder is None:
            self._runtime_embedder = FastEmbedder()
        return self._runtime_embedder

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY, title TEXT, url TEXT, doc_type TEXT,
                text TEXT, sha256 TEXT)"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY, doc_id TEXT, title TEXT, heading TEXT,
                url TEXT, text TEXT, sha256 TEXT, embedding BLOB)"""
        )
        return connection

    def build(self, *, force: bool = False) -> tuple[bool, float]:
        documents = load_corpus(self.corpus_path)
        corpus_sha = hashlib.sha256(
            "".join(document.sha256 for document in documents).encode()
        ).hexdigest()
        connection = self._connect()
        existing = connection.execute(
            "SELECT value FROM metadata WHERE key='corpus_sha256'"
        ).fetchone()
        if existing and existing[0] == corpus_sha and not force:
            connection.close()
            return False, 0.0
        chunks = [chunk for document in documents for chunk in chunk_document(document)]
        embedder = self._get_embedder()
        started = time.perf_counter()
        embeddings = embed_chunks(embedder, chunks)
        elapsed = time.perf_counter() - started
        with connection:
            connection.execute("DELETE FROM chunks")
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM metadata")
            connection.executemany(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        doc.doc_id,
                        doc.title,
                        doc.url,
                        doc.doc_type,
                        doc.text,
                        doc.sha256,
                    )
                    for doc in documents
                ],
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.title,
                        chunk.heading,
                        chunk.url,
                        chunk.text,
                        chunk.sha256,
                        embeddings[index].astype(np.float32).tobytes(),
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )
            connection.execute("INSERT INTO metadata VALUES ('corpus_sha256', ?)", (corpus_sha,))
            connection.execute(
                "INSERT INTO metadata VALUES ('embedding_dimensions', ?)",
                (str(embeddings.shape[1]),),
            )
        connection.close()
        return True, elapsed

    def ensure_built(self) -> None:
        if not self.path.exists():
            self.build()
            return
        connection = sqlite3.connect(self.path)
        row = connection.execute("SELECT value FROM metadata WHERE key='corpus_sha256'").fetchone()
        connection.close()
        documents = load_corpus(self.corpus_path)
        corpus_sha = hashlib.sha256(
            "".join(document.sha256 for document in documents).encode()
        ).hexdigest()
        if row is None or row[0] != corpus_sha:
            self.build()

    def documents(self) -> list[CorpusDocument]:
        connection = sqlite3.connect(self.path)
        rows = connection.execute(
            "SELECT doc_id, title, url, doc_type, text, sha256 FROM documents"
        ).fetchall()
        connection.close()
        return [CorpusDocument(*row) for row in rows]

    def get_document(self, doc_id: str) -> CorpusDocument | None:
        return next((doc for doc in self.documents() if doc.doc_id == doc_id), None)

    def document_for_url(self, url: str) -> CorpusDocument | None:
        return next((doc for doc in self.documents() if doc.url == url), None)

    def retrieve(self, query: str, *, top_k: int = 6) -> list[CorpusChunk]:
        self.ensure_built()
        connection = sqlite3.connect(self.path)
        rows = connection.execute(
            "SELECT chunk_id, doc_id, title, heading, url, text, sha256, embedding FROM chunks"
        ).fetchall()
        connection.close()
        chunks = [CorpusChunk(*row[:7]) for row in rows]
        embeddings = np.asarray(
            [np.frombuffer(row[7], dtype=np.float32) for row in rows],
            dtype=np.float32,
        )
        retriever = HybridRetriever(chunks, embeddings, self._get_embedder(), rrf_k=60)
        return retriever.retrieve(query, top_k=top_k)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build the local company corpus index")
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    index = CorpusIndex()
    changed, seconds = index.build(force=args.force)
    print(f"Index {'rebuilt' if changed else 'already current'}: {index.path}")
    if changed:
        print(f"Embedding build time: {seconds:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
