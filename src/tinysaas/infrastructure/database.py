"""PostgreSQL engine and session factory."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tinysaas.infrastructure.config import Settings


@dataclass(slots=True)
class Postgres:
    engine: AsyncEngine
    session_maker: async_sessionmaker[AsyncSession]

    async def ping(self) -> None:
        from sqlalchemy import text

        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()


def create_postgres(settings: Settings) -> Postgres:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    return Postgres(
        engine=engine,
        session_maker=async_sessionmaker(engine, expire_on_commit=False, autoflush=False),
    )
