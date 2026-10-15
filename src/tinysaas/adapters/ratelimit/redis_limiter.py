"""Redis sliding window limiter (atomic Lua script)."""

from __future__ import annotations

import secrets

import redis.asyncio as redis

from tinysaas.application.ports.external import RateLimitDecision

# KEYS[1] = bucket key
# ARGV[1] = window in milliseconds, ARGV[2] = limit, ARGV[3] = unique member
# returns {allowed, remaining, retry_after_seconds}
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window)
local used = redis.call('ZCARD', key)
if used < limit then
    redis.call('ZADD', key, now_ms, member)
    redis.call('PEXPIRE', key, window)
    return {1, limit - used - 1, 0}
end

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry_after = math.ceil(window / 1000)
if oldest[2] ~= nil then
    retry_after = math.max(1, math.ceil((tonumber(oldest[2]) + window - now_ms) / 1000))
end
return {0, 0, retry_after}
"""


class RedisRateLimiter:
    """Sliding window counter keyed by (route, client) pairs."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client
        self._script = client.register_script(_SLIDING_WINDOW_LUA)

    async def hit(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(
                allowed=False, limit=limit, remaining=0, retry_after_seconds=window_seconds
            )
        try:
            allowed, remaining, retry_after = await self._script(
                keys=[f"ratelimit:{key}"],
                args=[window_seconds * 1000, limit, secrets.token_hex(8)],
            )
        except Exception:
            # Fail open: a broken Redis must not take the whole API down.
            return RateLimitDecision(
                allowed=True, limit=limit, remaining=limit, retry_after_seconds=0
            )
        return RateLimitDecision(
            allowed=bool(int(allowed)),
            limit=limit,
            remaining=int(remaining),
            retry_after_seconds=int(retry_after),
        )
