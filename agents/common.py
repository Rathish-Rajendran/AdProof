from __future__ import annotations

import os
from pathlib import Path

from uagents import Agent
from uagents.resolver import RulesBasedResolver
from uagents_core.identity import Identity

from adproof.infrastructure.settings import Settings, load_or_create_seeds, write_public_addresses

PORTS = {"orchestrator": 8100, "verifier": 8101, "remediator": 8102}
TRANSPORT_TEST_CLIENT_SEED = "adproof-local-transport-session-proof"
SEED_ENV = {
    "orchestrator": "ORCHESTRATOR_SEED",
    "verifier": "VERIFIER_SEED",
    "remediator": "REMEDIATOR_SEED",
}


def load_identities(settings: Settings) -> tuple[dict[str, str], dict[str, str]]:
    supplied = {role: os.getenv(env_name) for role, env_name in SEED_ENV.items()}
    seeds = load_or_create_seeds(settings.runtime_dir, supplied)
    addresses = {role: Identity.from_seed(seed, 0).address for role, seed in seeds.items()}
    write_public_addresses(settings.runtime_dir, addresses)
    return seeds, addresses


def make_agent(
    *,
    role: str,
    seed: str,
    addresses: dict[str, str],
    port: int | None = None,
    concurrent: bool = False,
) -> Agent:
    own_port = port or int(os.getenv(f"{role.upper()}_PORT", PORTS[role]))
    own_endpoint = f"http://127.0.0.1:{own_port}/submit"
    endpoints = {
        addresses[
            peer
        ]: f"http://127.0.0.1:{int(os.getenv(f'{peer.upper()}_PORT', PORTS[peer]))}/submit"
        for peer in PORTS
        if peer != role
    }
    if role == "orchestrator" and os.getenv("ADPROOF_TRANSPORT_PROBE") == "1":
        test_client = Identity.from_seed(TRANSPORT_TEST_CLIENT_SEED, 0)
        endpoints[test_client.address] = "http://127.0.0.1:8110/submit"
    mailbox = os.getenv("ADPROOF_MAILBOX_ENABLED", "").casefold() in {"1", "true", "yes"}
    return Agent(
        name=f"adproof-{role}",
        seed=seed,
        port=own_port,
        endpoint=[own_endpoint],
        resolve=RulesBasedResolver(endpoints),
        mailbox=mailbox,
        handle_messages_concurrently=concurrent,
    )


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]
