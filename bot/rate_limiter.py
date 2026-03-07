from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# Telegram group limit is ~20 sends/min. Keep a small buffer.
_DEFAULT_MAX_PER_MINUTE = 18.0


class GroupRateLimiter:
    """Token-bucket rate limiter for Telegram sendMessage calls in a group.

    editMessageText uses a separate Telegram-side bucket, so only
    sendMessage (and similar send* methods) need to go through this.
    """

    def __init__(self, max_per_minute: float = _DEFAULT_MAX_PER_MINUTE) -> None:
        self._max = max_per_minute
        self._tokens: float = max_per_minute
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a send token is available."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            await asyncio.sleep(1.0)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._max, self._tokens + elapsed * (self._max / 60.0)
        )
        self._last_refill = now
