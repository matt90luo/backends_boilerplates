"""Schema helpers used by the CLI (create all / drop all)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tinysaas.adapters.persistence.models import Base


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
