from adproof.rag.chunker import CorpusChunk, CorpusDocument, chunk_document, load_corpus
from adproof.rag.retriever import HybridRetriever

__all__ = [
    "CorpusChunk",
    "CorpusDocument",
    "CorpusIndex",
    "HybridRetriever",
    "chunk_document",
    "load_corpus",
]


def __getattr__(name):
    if name == "CorpusIndex":
        from adproof.rag.index import CorpusIndex

        return CorpusIndex
    raise AttributeError(name)
