from adproof.infrastructure.settings import Settings
from adproof.rag.index import CorpusIndex
from agents.common import load_identities


def main() -> int:
    settings = Settings.from_env()
    _, addresses = load_identities(settings)
    built, elapsed = CorpusIndex(path=settings.runtime_dir / "corpus_index.sqlite3").build()
    print(f"Runtime prepared at {settings.runtime_dir.resolve()}")
    print(f"Corpus index built in {elapsed:.3f}s." if built else "Corpus index is already current.")
    for role, address in sorted(addresses.items()):
        print(f"{role}: {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
