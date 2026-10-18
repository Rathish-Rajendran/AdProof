from __future__ import annotations

import argparse
import asyncio
import json
import re

from uagents import Agent, Context
from uagents.resolver import RulesBasedResolver
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

from adproof.infrastructure.settings import Settings
from agents.common import PORTS, TRANSPORT_TEST_CLIENT_SEED, load_identities

_SESSION = re.compile(r"intake_session=([0-9a-f-]+)")


def run(*, workflow: bool = False) -> None:
    _, addresses = load_identities(Settings.from_env())
    agent = Agent(
        name="adproof-m1-client",
        seed=TRANSPORT_TEST_CLIENT_SEED,
        port=8110,
        endpoint=["http://127.0.0.1:8110/submit"],
        resolve=RulesBasedResolver(
            {addresses["orchestrator"]: f"http://127.0.0.1:{PORTS['orchestrator']}/submit"}
        ),
    )
    expected: set[str] = set()
    received: list[dict[str, str | bool]] = []
    workflow_messages: list[str] = []
    workflow_timer: asyncio.TimerHandle | None = None

    @agent.on_event("startup")
    async def start(ctx: Context) -> None:
        expected.add(str(ctx.session))
        commands = ("demo aerobeat",) if workflow else ("probe delayed", "probe timeout")
        for command in commands:
            await ctx.send(
                addresses["orchestrator"],
                ChatMessage(content=[TextContent(type="text", text=command)]),
            )

    @agent.on_message(ChatAcknowledgement)
    async def acknowledge(ctx: Context, sender: str, message: ChatAcknowledgement) -> None:
        return

    @agent.on_message(ChatMessage)
    async def receive(ctx: Context, sender: str, message: ChatMessage) -> None:
        text = message.text()
        if workflow:
            nonlocal workflow_timer
            workflow_messages.append(text)
            if workflow_timer is None:
                workflow_timer = asyncio.get_running_loop().call_later(
                    3,
                    lambda: print(
                        "LIVE_WORKFLOW_RESULT "
                        + json.dumps(
                            {
                                "client_session": str(ctx.session),
                                "report_chunks": workflow_messages,
                                "contains_original_repair_reverify": any(
                                    "Re-verification:" in item for item in workflow_messages
                                ),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    ),
                )
            return
        match = _SESSION.search(text)
        if not match:
            return
        session = str(ctx.session)
        received.append(
            {
                "text": text,
                "reply_session": session,
                "intake_session": match.group(1),
                "matches_original_client_session": session in expected
                and match.group(1) == session,
            }
        )
        if len(received) >= 2:
            print(
                "M1_PROOF "
                + json.dumps(
                    {
                        "expected_client_sessions": sorted(expected),
                        "replies": received,
                        "both_match": all(
                            item["matches_original_client_session"] for item in received
                        ),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    agent.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", action="store_true")
    run(workflow=parser.parse_args().workflow)
