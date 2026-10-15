"""Repository and unit of work ports.

Every query is expressed as a method on a port so that the SQLAlchemy adapters
and the in-memory test doubles are interchangeable.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from tinysaas.domain.billing.credits import CreditKind, CreditLedgerEntry
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import TopUp
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.catalog.service import Service
from tinysaas.domain.identity.api_key import ApiKey
from tinysaas.domain.identity.one_time_token import OneTimeToken, TokenKind
from tinysaas.domain.identity.session import RefreshToken
from tinysaas.domain.identity.user import User
from tinysaas.domain.invocation.invocation import Invocation, InvocationStatus


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def update(self, user: User) -> None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def list(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> tuple[list[User], int]: ...


class WalletRepository(Protocol):
    async def add(self, wallet: Wallet) -> None: ...

    async def update(self, wallet: Wallet) -> None: ...

    async def get(self, user_id: UUID) -> Wallet | None: ...

    async def get_for_update(self, user_id: UUID) -> Wallet | None:
        """Load the wallet with a row lock (``SELECT ... FOR UPDATE``)."""
        ...


class CreditLedgerRepository(Protocol):
    async def add(self, entry: CreditLedgerEntry) -> None: ...

    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int, kind: CreditKind | None = None
    ) -> tuple[list[CreditLedgerEntry], int]: ...


class CreditPackageRepository(Protocol):
    async def add(self, package: CreditPackage) -> None: ...

    async def list_active(self) -> list[CreditPackage]: ...

    async def get(self, package_id: UUID) -> CreditPackage | None: ...

    async def get_by_slug(self, slug: str) -> CreditPackage | None: ...


class ServiceRepository(Protocol):
    async def add(self, service: Service) -> None: ...

    async def update(self, service: Service) -> None: ...

    async def get(self, service_id: UUID) -> Service | None: ...

    async def get_by_slug(self, slug: str) -> Service | None: ...

    async def list(
        self, *, include_inactive: bool, limit: int, offset: int
    ) -> tuple[list[Service], int]: ...


class InvocationRepository(Protocol):
    async def add(self, invocation: Invocation) -> None: ...

    async def update(self, invocation: Invocation) -> None: ...

    async def get(self, invocation_id: UUID) -> Invocation | None: ...

    async def get_by_idempotency_key(
        self, user_id: UUID, idempotency_key: str
    ) -> Invocation | None: ...

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        status: InvocationStatus | None = None,
        service_slug: str | None = None,
    ) -> tuple[list[Invocation], int]: ...

    async def list_all(
        self,
        *,
        limit: int,
        offset: int,
        user_id: UUID | None = None,
        status: InvocationStatus | None = None,
        service_slug: str | None = None,
    ) -> tuple[list[Invocation], int]: ...

    async def count_since(self, user_id: UUID, since: datetime) -> int: ...


class TopUpRepository(Protocol):
    async def add(self, topup: TopUp) -> None: ...

    async def add_or_get(self, topup: TopUp) -> tuple[TopUp, bool]:
        """Insert unless the same ``(user_id, idempotency_key)`` already exists."""
        ...

    async def update(self, topup: TopUp) -> None: ...

    async def get(self, topup_id: UUID) -> TopUp | None: ...

    async def get_by_idempotency_key(self, user_id: UUID, idempotency_key: str) -> TopUp | None: ...

    async def get_by_checkout_session(self, session_id: str) -> TopUp | None: ...


class RefreshTokenRepository(Protocol):
    async def add(self, token: RefreshToken) -> None: ...

    async def update(self, token: RefreshToken) -> None: ...

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    async def get(self, token_id: UUID) -> RefreshToken | None: ...

    async def list_active_for_user(self, user_id: UUID, *, now: datetime) -> list[RefreshToken]: ...

    async def revoke_family(self, family_id: UUID, *, now: datetime) -> int: ...

    async def revoke_all_for_user(self, user_id: UUID, *, now: datetime) -> int: ...


class ApiKeyRepository(Protocol):
    async def add(self, api_key: ApiKey) -> None: ...

    async def update(self, api_key: ApiKey) -> None: ...

    async def get(self, key_id: UUID) -> ApiKey | None: ...

    async def get_by_prefix(self, prefix: str) -> ApiKey | None: ...

    async def list_for_user(self, user_id: UUID) -> list[ApiKey]: ...


class OneTimeTokenRepository(Protocol):
    async def add(self, token: OneTimeToken) -> None: ...

    async def update(self, token: OneTimeToken) -> None: ...

    async def get_by_hash(self, token_hash: str) -> OneTimeToken | None: ...

    async def invalidate_active(self, user_id: UUID, kind: TokenKind, *, now: datetime) -> int: ...


class ProcessedEventRepository(Protocol):
    async def add_if_new(
        self, *, event_id: str, event_type: str, reference: str | None = None
    ) -> bool: ...


class UnitOfWork(Protocol):
    """One business transaction: repositories plus commit/rollback.

    Members are declared as read-only properties so that implementations may
    expose narrower (concrete) repository types.
    """

    @property
    def users(self) -> UserRepository: ...

    @property
    def wallets(self) -> WalletRepository: ...

    @property
    def ledger(self) -> CreditLedgerRepository: ...

    @property
    def packages(self) -> CreditPackageRepository: ...

    @property
    def services(self) -> ServiceRepository: ...

    @property
    def invocations(self) -> InvocationRepository: ...

    @property
    def topups(self) -> TopUpRepository: ...

    @property
    def refresh_tokens(self) -> RefreshTokenRepository: ...

    @property
    def api_keys(self) -> ApiKeyRepository: ...

    @property
    def one_time_tokens(self) -> OneTimeTokenRepository: ...

    @property
    def processed_events(self) -> ProcessedEventRepository: ...

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
