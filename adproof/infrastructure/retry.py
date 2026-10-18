from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

T = TypeVar("T")


async def retry_once(
    operation: Callable[[], Awaitable[T]],
    *,
    deadline: datetime,
    retryable: Callable[[Exception], bool],
    backoff_seconds: float = 0.1,
) -> T:
    for attempt in range(2):
        try:
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise TimeoutError("deadline expired")
            return await asyncio.wait_for(operation(), timeout=remaining)
        except Exception as exc:
            if attempt or not retryable(exc):
                raise
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            delay = backoff_seconds * random.uniform(0.5, 1.5)
            if remaining <= delay:
                raise TimeoutError("deadline expired before retry") from exc
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")
