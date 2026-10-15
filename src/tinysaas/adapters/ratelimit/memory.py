"""In-process limiter used by tests and single node development."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from tinysaas.application.ports.external import RateLimitDecision

_MAX_TRACKED_KEYS = 10_000


class InMemoryRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self._clock()
        if len(self._buckets) > _MAX_TRACKED_KEYS:
            self._buckets.clear()
        bucket = self._buckets[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            return RateLimitDecision(
                allowed=False, limit=limit, remaining=0, retry_after_seconds=retry_after
            )
        bucket.append(now)
        return RateLimitDecision(
            allowed=True, limit=limit, remaining=limit - len(bucket), retry_after_seconds=0
        )
