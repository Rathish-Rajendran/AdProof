import numpy as np

from adproof.rag.chunker import CorpusDocument, chunk_document
from adproof.rag.retriever import HybridRetriever


class FakeEmbedder:
    def embed(self, texts):
        for text in texts:
            tokens = set(text.casefold().split())
            yield np.array(
                [len(tokens & {"battery", "waterproof"}), len(tokens & {"price", "discount"})],
                dtype=np.float32,
            )


def test_chunker_prefixes_heading_and_uses_stable_ids():
    document = CorpusDocument(
        "doc",
        "Product",
        "https://example.test/product",
        "product_page",
        "# Facts\nBattery life is 30 hours. " * 60,
        "hash",
    )
    chunks = chunk_document(document)
    assert chunks[0].chunk_id == "doc#1"
    assert "Product — Facts" in chunks[0].text
    assert len(chunks) > 1


def test_hybrid_retriever_returns_relevant_chunks():
    chunks = [
        type("Chunk", (), {"chunk_id": "a", "text": "battery life 30 hours"})(),
        type("Chunk", (), {"chunk_id": "b", "text": "price 60 dollars discount"})(),
    ]
    vectors = np.asarray([[1, 0], [0, 1]], dtype=np.float32)
    result = HybridRetriever(chunks, vectors, FakeEmbedder()).retrieve("battery", top_k=1)
    assert result[0].chunk_id == "a"
