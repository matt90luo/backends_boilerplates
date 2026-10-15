"""Integration tests against the local PostgreSQL instance.

Run with::

    uv run pytest -m integration tests/integration

They use ``DATABASE_URL`` (defaults to the local ``tests`` database). Rows they
create are deleted afterwards (``DELETE FROM users`` cascades to every child
table), and the schema is only dropped when this test created it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tinysaas.adapters.persistence.models import Base, UserRow
from tinysaas.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from tinysaas.domain.billing.credits import CreditAmount
from tinysaas.domain.billing.wallet import InsufficientCredits, Wallet
from tinysaas.domain.catalog.service import Service
from tinysaas.domain.identity.user import User
from tinysaas.infrastructure.config import get_settings
from tinysaas.infrastructure.database import create_postgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _prepare_schema(engine: AsyncEngine) -> bool:
    """Ensure the tables exist; return True when this call created them."""
    created = False

    def _has_users(sync_engine: Connection) -> bool:
        return bool(inspect(sync_engine).has_table("users"))

    async with engine.connect() as connection:
        created = not await connection.run_sync(_has_users)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return created


async def _cleanup(engine: AsyncEngine, *, user_id: object, created_schema: bool) -> None:
    if created_schema:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
    else:
        async with engine.begin() as connection:
            await connection.execute(delete(UserRow).where(UserRow.id == user_id))


async def test_unit_of_work_round_trip_and_row_locking() -> None:
    settings = get_settings()
    postgres = create_postgres(settings)
    session_factory = async_sessionmaker(postgres.engine, expire_on_commit=False)
    now = datetime.now(UTC)
    user = User.register(email=f"it-{uuid4().hex[:8]}@example.com", password_hash="x", now=now)
    created_schema = await _prepare_schema(postgres.engine)

    factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    try:
        async with factory() as uow:
            await uow.users.add(user)
            wallet = Wallet.for_user(user.id, now=now)
            top_up = wallet.top_up(CreditAmount(5), reference="it", now=now)
            await uow.wallets.add(wallet)
            await uow.ledger.add(top_up)
            await uow.commit()

        async with factory() as uow:
            locked = await uow.wallets.get_for_update(user.id)
            assert locked is not None
            entry = locked.reserve(CreditAmount(1), invocation_id=uuid4())
            await uow.wallets.update(locked)
            await uow.ledger.add(entry)
            await uow.commit()

        async with factory() as uow:
            reloaded = await uow.wallets.get(user.id)
            assert reloaded is not None and reloaded.reserved == 1 and reloaded.balance == 4
            assert (await uow.users.get_by_email(user.email)) is not None
            entries, total = await uow.ledger.list_for_user(user.id, limit=10, offset=0)
            assert total == 2 and [e.kind.value for e in entries] == ["reserve", "topup"]

        async with factory() as uow:
            service = Service.create(slug=f"it-{uuid4().hex[:6]}", name="IT", credit_cost=2)
            await uow.services.add(service)
            await uow.commit()
        async with factory() as uow:
            loaded = await uow.services.get_by_slug(service.slug)
            assert loaded is not None and loaded.credit_cost == 2
    finally:
        await _cleanup(postgres.engine, user_id=user.id, created_schema=created_schema)
        await postgres.dispose()


async def test_wallet_constraint_survives_a_real_database() -> None:
    settings = get_settings()
    postgres = create_postgres(settings)
    session_factory = async_sessionmaker(postgres.engine, expire_on_commit=False)
    now = datetime.now(UTC)
    user = User.register(email=f"it-{uuid4().hex[:8]}@example.com", password_hash="x", now=now)
    factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    created_schema = await _prepare_schema(postgres.engine)

    try:
        async with factory() as uow:
            await uow.users.add(user)
            await uow.wallets.add(Wallet.for_user(user.id, now=now))
            await uow.commit()

        with pytest.raises(InsufficientCredits):
            async with factory() as uow:
                locked = await uow.wallets.get_for_update(user.id)
                assert locked is not None
                locked.reserve(CreditAmount(5), invocation_id=uuid4())
    finally:
        await _cleanup(postgres.engine, user_id=user.id, created_schema=created_schema)
        await postgres.dispose()
