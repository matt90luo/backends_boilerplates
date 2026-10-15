"""In-memory repositories and unit of work.

Reads return deep copies so that a use case mutating an entity cannot silently
change the store without an explicit ``update`` (mirroring a real database).
``commit()`` is a no-op because every write is applied immediately.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import TracebackType
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


class MemoryStore:
    """Plain dictionaries standing in for database tables."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.wallets: dict[UUID, Wallet] = {}
        self.ledger: dict[UUID, CreditLedgerEntry] = {}
        self.packages: dict[UUID, CreditPackage] = {}
        self.services: dict[UUID, Service] = {}
        self.invocations: dict[UUID, Invocation] = {}
        self.topups: dict[UUID, TopUp] = {}
        self.refresh_tokens: dict[UUID, RefreshToken] = {}
        self.api_keys: dict[UUID, ApiKey] = {}
        self.one_time_tokens: dict[UUID, OneTimeToken] = {}
        self.processed_events: dict[str, str] = {}

    # convenience used by the tests -------------------------------------
    def add_package(self, package: CreditPackage) -> CreditPackage:
        self.packages[package.id] = package
        return package

    def add_service(self, service: Service) -> Service:
        self.services[service.id] = service
        return service

    def wallet_of(self, user_id: UUID) -> Wallet | None:
        return self.wallets.get(user_id)


class MemoryUserRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, user: User) -> None:
        self._store.users[user.id] = deepcopy(user)

    async def update(self, user: User) -> None:
        self._store.users[user.id] = deepcopy(user)

    async def get(self, user_id: UUID) -> User | None:
        user = self._store.users.get(user_id)
        return deepcopy(user) if user else None

    async def get_by_email(self, email: str) -> User | None:
        for user in self._store.users.values():
            if user.email == email.strip().lower():
                return deepcopy(user)
        return None

    async def list(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> tuple[list[User], int]:
        users = sorted(self._store.users.values(), key=lambda u: u.created_at, reverse=True)
        if search:
            needle = search.strip().lower()
            users = [
                user
                for user in users
                if needle in user.email.lower() or needle in (user.display_name or "").lower()
            ]
        return [deepcopy(user) for user in users[offset : offset + limit]], len(users)


class MemoryWalletRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, wallet: Wallet) -> None:
        self._store.wallets[wallet.user_id] = deepcopy(wallet)

    async def update(self, wallet: Wallet) -> None:
        self._store.wallets[wallet.user_id] = deepcopy(wallet)

    async def get(self, user_id: UUID) -> Wallet | None:
        wallet = self._store.wallets.get(user_id)
        return deepcopy(wallet) if wallet else None

    async def get_for_update(self, user_id: UUID) -> Wallet | None:
        return await self.get(user_id)


class MemoryCreditLedgerRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, entry: CreditLedgerEntry) -> None:
        self._store.ledger[entry.id] = entry

    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int, kind: CreditKind | None = None
    ) -> tuple[list[CreditLedgerEntry], int]:
        entries = [
            entry
            for entry in self._store.ledger.values()
            if entry.user_id == user_id and (kind is None or entry.kind is kind)
        ]
        entries.sort(key=lambda entry: entry.created_at, reverse=True)
        return entries[offset : offset + limit], len(entries)


class MemoryCreditPackageRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, package: CreditPackage) -> None:
        self._store.packages[package.id] = package

    async def list_active(self) -> list[CreditPackage]:
        packages = [p for p in self._store.packages.values() if p.is_active]
        return sorted(packages, key=lambda p: p.credits)

    async def get(self, package_id: UUID) -> CreditPackage | None:
        return self._store.packages.get(package_id)

    async def get_by_slug(self, slug: str) -> CreditPackage | None:
        for package in self._store.packages.values():
            if package.slug == slug:
                return package
        return None


class MemoryServiceRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, service: Service) -> None:
        self._store.services[service.id] = deepcopy(service)

    async def update(self, service: Service) -> None:
        self._store.services[service.id] = deepcopy(service)

    async def get(self, service_id: UUID) -> Service | None:
        service = self._store.services.get(service_id)
        return deepcopy(service) if service else None

    async def get_by_slug(self, slug: str) -> Service | None:
        for service in self._store.services.values():
            if service.slug == slug:
                return deepcopy(service)
        return None

    async def list(
        self, *, include_inactive: bool, limit: int, offset: int
    ) -> tuple[list[Service], int]:
        services = [
            service
            for service in self._store.services.values()
            if include_inactive or service.is_active
        ]
        services.sort(key=lambda service: service.created_at, reverse=True)
        return [deepcopy(s) for s in services[offset : offset + limit]], len(services)


class MemoryInvocationRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, invocation: Invocation) -> None:
        self._store.invocations[invocation.id] = deepcopy(invocation)

    async def update(self, invocation: Invocation) -> None:
        self._store.invocations[invocation.id] = deepcopy(invocation)

    async def get(self, invocation_id: UUID) -> Invocation | None:
        invocation = self._store.invocations.get(invocation_id)
        return deepcopy(invocation) if invocation else None

    async def get_by_idempotency_key(
        self, user_id: UUID, idempotency_key: str
    ) -> Invocation | None:
        for invocation in self._store.invocations.values():
            if invocation.user_id == user_id and invocation.idempotency_key == idempotency_key:
                return deepcopy(invocation)
        return None

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        status: InvocationStatus | None = None,
        service_slug: str | None = None,
    ) -> tuple[list[Invocation], int]:
        return self._filtered(
            limit=limit, offset=offset, user_id=user_id, status=status, service_slug=service_slug
        )

    async def list_all(
        self,
        *,
        limit: int,
        offset: int,
        user_id: UUID | None = None,
        status: InvocationStatus | None = None,
        service_slug: str | None = None,
    ) -> tuple[list[Invocation], int]:
        return self._filtered(
            limit=limit, offset=offset, user_id=user_id, status=status, service_slug=service_slug
        )

    async def count_since(self, user_id: UUID, since: datetime) -> int:
        return sum(
            1
            for invocation in self._store.invocations.values()
            if invocation.user_id == user_id and invocation.created_at >= since
        )

    def _filtered(
        self,
        *,
        limit: int,
        offset: int,
        user_id: UUID | None,
        status: InvocationStatus | None,
        service_slug: str | None,
    ) -> tuple[list[Invocation], int]:
        rows = [
            invocation
            for invocation in self._store.invocations.values()
            if (user_id is None or invocation.user_id == user_id)
            and (status is None or invocation.status is status)
            and (service_slug is None or invocation.service_slug == service_slug)
        ]
        rows.sort(key=lambda invocation: invocation.created_at, reverse=True)
        return [deepcopy(row) for row in rows[offset : offset + limit]], len(rows)


class MemoryTopUpRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, topup: TopUp) -> None:
        self._store.topups[topup.id] = deepcopy(topup)

    async def add_or_get(self, topup: TopUp) -> tuple[TopUp, bool]:
        for existing in self._store.topups.values():
            if (
                existing.user_id == topup.user_id
                and existing.idempotency_key == topup.idempotency_key
            ):
                return deepcopy(existing), False
        self._store.topups[topup.id] = deepcopy(topup)
        return deepcopy(topup), True

    async def update(self, topup: TopUp) -> None:
        self._store.topups[topup.id] = deepcopy(topup)

    async def get(self, topup_id: UUID) -> TopUp | None:
        topup = self._store.topups.get(topup_id)
        return deepcopy(topup) if topup else None

    async def get_by_idempotency_key(self, user_id: UUID, idempotency_key: str) -> TopUp | None:
        for topup in self._store.topups.values():
            if topup.user_id == user_id and topup.idempotency_key == idempotency_key:
                return deepcopy(topup)
        return None

    async def get_by_checkout_session(self, session_id: str) -> TopUp | None:
        for topup in self._store.topups.values():
            if topup.checkout_session_id == session_id:
                return deepcopy(topup)
        return None


class MemoryRefreshTokenRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, token: RefreshToken) -> None:
        self._store.refresh_tokens[token.id] = deepcopy(token)

    async def update(self, token: RefreshToken) -> None:
        self._store.refresh_tokens[token.id] = deepcopy(token)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        for token in self._store.refresh_tokens.values():
            if token.token_hash == token_hash:
                return deepcopy(token)
        return None

    async def get(self, token_id: UUID) -> RefreshToken | None:
        token = self._store.refresh_tokens.get(token_id)
        return deepcopy(token) if token else None

    async def list_active_for_user(self, user_id: UUID, *, now: datetime) -> list[RefreshToken]:
        tokens = [
            token
            for token in self._store.refresh_tokens.values()
            if token.user_id == user_id and token.is_active(now=now)
        ]
        tokens.sort(key=lambda token: token.created_at, reverse=True)
        return [deepcopy(token) for token in tokens]

    async def revoke_family(self, family_id: UUID, *, now: datetime) -> int:
        count = 0
        for token_id, token in list(self._store.refresh_tokens.items()):
            if token.family_id == family_id and not token.is_revoked:
                token.revoke(now=now)
                self._store.refresh_tokens[token_id] = deepcopy(token)
                count += 1
        return count

    async def revoke_all_for_user(self, user_id: UUID, *, now: datetime) -> int:
        count = 0
        for token_id, token in list(self._store.refresh_tokens.items()):
            if token.user_id == user_id and not token.is_revoked:
                token.revoke(now=now)
                self._store.refresh_tokens[token_id] = deepcopy(token)
                count += 1
        return count


class MemoryApiKeyRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, api_key: ApiKey) -> None:
        self._store.api_keys[api_key.id] = deepcopy(api_key)

    async def update(self, api_key: ApiKey) -> None:
        self._store.api_keys[api_key.id] = deepcopy(api_key)

    async def get(self, key_id: UUID) -> ApiKey | None:
        api_key = self._store.api_keys.get(key_id)
        return deepcopy(api_key) if api_key else None

    async def get_by_prefix(self, prefix: str) -> ApiKey | None:
        for api_key in self._store.api_keys.values():
            if api_key.prefix == prefix:
                return deepcopy(api_key)
        return None

    async def list_for_user(self, user_id: UUID) -> list[ApiKey]:
        keys = [key for key in self._store.api_keys.values() if key.user_id == user_id]
        keys.sort(key=lambda key: key.created_at, reverse=True)
        return [deepcopy(key) for key in keys]


class MemoryOneTimeTokenRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add(self, token: OneTimeToken) -> None:
        self._store.one_time_tokens[token.id] = deepcopy(token)

    async def update(self, token: OneTimeToken) -> None:
        self._store.one_time_tokens[token.id] = deepcopy(token)

    async def get_by_hash(self, token_hash: str) -> OneTimeToken | None:
        for token in self._store.one_time_tokens.values():
            if token.token_hash == token_hash:
                return deepcopy(token)
        return None

    async def invalidate_active(self, user_id: UUID, kind: TokenKind, *, now: datetime) -> int:
        count = 0
        for token_id, token in list(self._store.one_time_tokens.items()):
            if token.user_id == user_id and token.kind is kind and token.used_at is None:
                token.consume(now=now)
                self._store.one_time_tokens[token_id] = deepcopy(token)
                count += 1
        return count


class MemoryProcessedEventRepository:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def add_if_new(
        self, *, event_id: str, event_type: str, reference: str | None = None
    ) -> bool:
        if event_id in self._store.processed_events:
            return False
        self._store.processed_events[event_id] = event_type
        return True


class InMemoryUnitOfWork:
    """Implements the ``UnitOfWork`` port on top of :class:`MemoryStore`."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self.users = MemoryUserRepository(store)
        self.wallets = MemoryWalletRepository(store)
        self.ledger = MemoryCreditLedgerRepository(store)
        self.packages = MemoryCreditPackageRepository(store)
        self.services = MemoryServiceRepository(store)
        self.invocations = MemoryInvocationRepository(store)
        self.topups = MemoryTopUpRepository(store)
        self.refresh_tokens = MemoryRefreshTokenRepository(store)
        self.api_keys = MemoryApiKeyRepository(store)
        self.one_time_tokens = MemoryOneTimeTokenRepository(store)
        self.processed_events = MemoryProcessedEventRepository(store)

    async def __aenter__(self) -> InMemoryUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        """No-op: this fake applies writes immediately."""

    async def rollback(self) -> None:
        """No-op: see :meth:`commit`."""


class InMemoryUnitOfWorkFactory:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def __call__(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self._store)
