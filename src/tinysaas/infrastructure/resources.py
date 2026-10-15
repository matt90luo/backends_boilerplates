"""Long lived resources: engine, redis pool, s3 client, http client, arq pool.

The object is constructed synchronously (no I/O: just drivers) and its
lifecycle is explicit through :meth:`Resources.start` / :meth:`Resources.shutdown`.
``ResourceManager`` used to be exposed as ``providers.Resource``; keeping the
construction synchronous keeps the whole object graph synchronous, which makes
the container predictable (``container.use_case()`` returns an object, not a
future) while still giving the app a single place to open and close connections.
"""

from __future__ import annotations

import httpx
import redis.asyncio as redis
import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from tinysaas.application.ports.external import ReadinessProbe
from tinysaas.infrastructure.config import Settings
from tinysaas.infrastructure.database import Postgres, create_postgres
from tinysaas.infrastructure.probes import PostgresProbe, RedisProbe, StorageProbe
from tinysaas.infrastructure.redis_client import create_redis
from tinysaas.infrastructure.s3 import S3Storage, create_s3_storage

logger = structlog.get_logger("tinysaas.resources")


class Resources:
    """Owns every connection this process holds."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.postgres: Postgres = create_postgres(settings)
        self.redis: redis.Redis = create_redis(settings)
        self.s3: S3Storage = create_s3_storage(settings)
        self.http_client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_proxy_timeout_seconds, connect=10.0),
            follow_redirects=False,
        )
        self.arq_pool: ArqRedis | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> Resources:
        """Open the resources that need an event loop (idempotent)."""
        if self._started:
            return self
        try:
            self.arq_pool = await create_pool(RedisSettings.from_dsn(self.settings.redis_url))
        except Exception as error:  # pragma: no cover - depends on the environment
            logger.warning("arq_pool_unavailable", error=str(error))
            self.arq_pool = None
        if self.settings.storage_backend == "s3" and self.settings.s3_auto_create_bucket:
            try:
                await self.s3.ensure_bucket()
            except Exception as error:  # pragma: no cover - depends on the environment
                logger.warning("s3_bucket_unavailable", error=str(error))
        self._started = True
        return self

    async def shutdown(self) -> None:
        """Release everything; safe to call even if :meth:`start` never ran."""
        if self._started:
            await self.http_client.aclose()
            if self.arq_pool is not None:
                await self.arq_pool.aclose()
                self.arq_pool = None
            self._started = False
        await self.postgres.dispose()
        await self.redis.aclose()

    def readiness_probes(self) -> list[ReadinessProbe]:
        return [
            PostgresProbe(self.postgres),
            RedisProbe(self.redis),
            StorageProbe(self.s3),
        ]
