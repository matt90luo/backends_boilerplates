"""SQLAlchemy unit of work."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tinysaas.adapters.persistence.repositories import (
    SqlAlchemyApiKeyRepository,
    SqlAlchemyCreditLedgerRepository,
    SqlAlchemyCreditPackageRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyOneTimeTokenRepository,
    SqlAlchemyProcessedEventRepository,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyServiceRepository,
    SqlAlchemyTopUpRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWalletRepository,
)


class SqlAlchemyUnitOfWork:
    """One transaction; repositories share the same session.

    ``commit()`` must be called explicitly by the use case, which keeps the
    transaction boundary visible in the application layer. Leaving the context
    without committing rolls everything back.
    """

    users: SqlAlchemyUserRepository
    wallets: SqlAlchemyWalletRepository
    ledger: SqlAlchemyCreditLedgerRepository
    packages: SqlAlchemyCreditPackageRepository
    services: SqlAlchemyServiceRepository
    invocations: SqlAlchemyInvocationRepository
    topups: SqlAlchemyTopUpRepository
    refresh_tokens: SqlAlchemyRefreshTokenRepository
    api_keys: SqlAlchemyApiKeyRepository
    one_time_tokens: SqlAlchemyOneTimeTokenRepository
    processed_events: SqlAlchemyProcessedEventRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._committed = False
        self.users = SqlAlchemyUserRepository(self._session)
        self.wallets = SqlAlchemyWalletRepository(self._session)
        self.ledger = SqlAlchemyCreditLedgerRepository(self._session)
        self.packages = SqlAlchemyCreditPackageRepository(self._session)
        self.services = SqlAlchemyServiceRepository(self._session)
        self.invocations = SqlAlchemyInvocationRepository(self._session)
        self.topups = SqlAlchemyTopUpRepository(self._session)
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(self._session)
        self.api_keys = SqlAlchemyApiKeyRepository(self._session)
        self.one_time_tokens = SqlAlchemyOneTimeTokenRepository(self._session)
        self.processed_events = SqlAlchemyProcessedEventRepository(self._session)
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        try:
            if exception_type is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()
        self._committed = False

    async def commit(self) -> None:
        await self.session.commit()
        self._committed = True

    async def rollback(self) -> None:
        await self.session.rollback()
        self._committed = False


class SqlAlchemyUnitOfWorkFactory:
    """Callable factory so use cases can open a transaction per operation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)
