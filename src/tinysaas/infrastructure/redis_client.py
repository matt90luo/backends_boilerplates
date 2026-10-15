"""Redis client and a tiny atomic counter used by the rate limiter."""

from __future__ import annotations

import redis.asyncio as redis

from tinysaas.infrastructure.config import Settings


def create_redis(settings: Settings) -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


async def ping_redis(client: redis.Redis) -> None:
    await client.ping()
