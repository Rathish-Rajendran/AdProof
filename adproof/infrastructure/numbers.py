from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"(?P<currency>\$)?(?P<value>\d[\d,]*(?:\.\d+)?)(?P<percent>%?)")


def number_tokens(text: str) -> set[tuple[bool, Decimal, bool]]:
    tokens = set()
    for match in _NUMBER.finditer(text):
        try:
            value = Decimal(match.group("value").replace(",", ""))
        except InvalidOperation:
            continue
        tokens.add((bool(match.group("currency")), value, bool(match.group("percent"))))
    return tokens
