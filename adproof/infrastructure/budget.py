from __future__ import annotations

import asyncio

from adproof.domain.models import TypedErrorCode


class BudgetExhausted(RuntimeError):
    code = TypedErrorCode.BUDGET_EXHAUSTED


class ModelCallBudget:
    def __init__(self, limit: int = 20):
        self.limit = limit
        self.consumed = 0
        self.reserved = 0
        self._lock = asyncio.Lock()

    async def reserve(self, count: int = 1) -> None:
        async with self._lock:
            if count < 1 or self.consumed + self.reserved + count > self.limit:
                raise BudgetExhausted("model-call budget exhausted")
            self.reserved += count

    async def consume(self, count: int = 1) -> None:
        async with self._lock:
            if count < 1 or count > self.reserved:
                raise ValueError("cannot consume unreserved model calls")
            self.reserved -= count
            self.consumed += count

    async def release(self, count: int = 1) -> None:
        async with self._lock:
            self.reserved -= min(max(count, 0), self.reserved)

    async def grant(self, count: int) -> int:
        async with self._lock:
            return max(0, min(count, self.limit - self.consumed - self.reserved))
