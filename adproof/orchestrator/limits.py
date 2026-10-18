from __future__ import annotations

import asyncio


class OwnerAuditLimiter:
    def __init__(self, limit: int = 2):
        self.limit = limit
        self._active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, owner: str) -> bool:
        async with self._lock:
            active = self._active.get(owner, 0)
            if active >= self.limit:
                return False
            self._active[owner] = active + 1
            return True

    async def release(self, owner: str) -> None:
        async with self._lock:
            active = self._active.get(owner, 0)
            if active <= 1:
                self._active.pop(owner, None)
            else:
                self._active[owner] = active - 1
