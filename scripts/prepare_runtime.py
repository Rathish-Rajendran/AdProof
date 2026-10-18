from adproof.infrastructure.settings import Settings
from agents.common import load_identities


def main() -> int:
    settings = Settings.from_env()
    _, addresses = load_identities(settings)
    print(f"Runtime prepared at {settings.runtime_dir.resolve()}")
    for role, address in sorted(addresses.items()):
        print(f"{role}: {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
