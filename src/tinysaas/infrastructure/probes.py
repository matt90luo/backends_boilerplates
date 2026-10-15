"""Readiness probes for the dependencies behind ``/readyz``."""

from __future__ import annotations

import redis.asyncio as redis

from tinysaas.infrastructure.database import Postgres
from tinysaas.infrastructure.s3 import S3Storage


class PostgresProbe:
    name = "postgres"

    def __init__(self, postgres: Postgres) -> None:
        self._postgres = postgres

    async def ping(self) -> None:
        await self._postgres.ping()


class RedisProbe:
    name = "redis"

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def ping(self) -> None:
        await self._client.ping()


class StorageProbe:
    name = "storage"

    def __init__(self, storage: S3Storage) -> None:
        self._storage = storage

    async def ping(self) -> None:
        await self._storage.ping()
