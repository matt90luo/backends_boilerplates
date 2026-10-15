"""Integration test for the Redis sliding window limiter."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tinysaas.adapters.ratelimit.redis_limiter import RedisRateLimiter
from tinysaas.infrastructure.config import get_settings
from tinysaas.infrastructure.redis_client import create_redis

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_sliding_window_allows_then_blocks() -> None:
    client = create_redis(get_settings())
    limiter = RedisRateLimiter(client)
    key = f"it:{uuid4().hex}"
    try:
        decisions = [await limiter.hit(key=key, limit=3, window_seconds=60) for _ in range(4)]
        assert [decision.allowed for decision in decisions] == [True, True, True, False]
        assert decisions[-1].retry_after_seconds >= 1
        assert decisions[0].remaining == 2
    finally:
        await client.delete(f"ratelimit:{key}")
        await client.aclose()
