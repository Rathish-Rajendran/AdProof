import re
from pathlib import Path

CORPUS = Path(__file__).parents[1] / "data/corpus/aerobeat"


def test_ab01_corpus_contains_the_documented_facts_only():
    contents = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(CORPUS.glob("*.md"))
        if "AB-01" in path.read_text(encoding="utf-8")
    )
    for fact in (
        "$80",
        "$60",
        "25%",
        "up to 30 hours",
        "up to 22 hours",
        "IPX4",
        "Bluetooth 5.3",
        "10-minute charge",
        "3 hours",
        "USB-C",
        "250 g",
        "1-year limited warranty",
        "30-day",
    ):
        assert fact in contents
    for match in re.finditer(r"\bwaterproof\b", contents, re.IGNORECASE):
        assert contents[max(0, match.start() - 4) : match.start()].lower() == "not "
    for path in CORPUS.glob("*.md"):
        assert "synthetic" in path.read_text(encoding="utf-8").lower()


def test_corpus_is_realistic_sized_and_old_retrieval_cards_are_removed():
    documents = list(CORPUS.glob("*.md"))
    total_bytes = sum(path.stat().st_size for path in documents)

    assert 35_000 <= total_bytes <= 50_000
    assert not (CORPUS / "ab01-retrieval-cards.md").exists()
    assert not (CORPUS / "ab01-fact-ledger.md").exists()
