from agents.orchestrator.main import strip_leading_mentions


def test_asi_one_mentions_are_stripped_before_command_matching():
    address = "agent1q0lpgrz6c80h2n5ns0vw5sq0wtrp8gkm92x3pl6n5hwru7z0f47977ntemy"
    assert strip_leading_mentions(f"@{address} help") == "help"
    assert strip_leading_mentions(f"  @{address}   demo aerobeat ") == "demo aerobeat"
    assert strip_leading_mentions("@adproof-orchestrator, status abc") == "status abc"
    assert strip_leading_mentions("help") == "help"
    assert strip_leading_mentions("email me@example.com") == "email me@example.com"
