"""Repository implementations on top of SQLAlchemy sessions.

Every method flushes so that constraints surface inside the surrounding
transaction (the unit of work owns commit/rollback).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from tinysaas.adapters.persistence import mapping as m
from tinysaas.adapters.persistence.models import (
    ApiKeyRow,
    CreditLedgerRow,
    CreditPackageRow,
    InvocationRow,
    OneTimeTokenRow,
    ProcessedStripeEventRow,
    RefreshTokenRow,
    ServiceRow,
    TopUpRow,
    UserRow,
    WalletRow,
)
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


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(m.new_user_row(user))
        await self._session.flush()

    async def update(self, user: User) -> None:
        row = await self._session.get(UserRow, user.id)
        if row is None:
            raise LookupError(f"user {user.id} does not exist")
        m.apply_user(row, user)
        await self._session.flush()

    async def get(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return m.to_user(row) if row is not None else None

    async def get_by_email(self, email: str) -> User | None:
        row = await self._session.scalar(select(UserRow).where(UserRow.email == email))
        return m.to_user(row) if row is not None else None

    async def list(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> tuple[list[User], int]:
        criteria = []
        if search:
            pattern = f"%{search.strip().lower()}%"
            criteria.append(
                or_(
                    func.lower(UserRow.email).like(pattern),
                    func.lower(func.coalesce(UserRow.display_name, "")).like(pattern),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(UserRow).where(*criteria)
        )
        rows = await self._session.scalars(
            select(UserRow)
            .where(*criteria)
            .order_by(UserRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [m.to_user(row) for row in rows], int(total or 0)


class SqlAlchemyWalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, wallet: Wallet) -> None:
        self._session.add(m.new_wallet_row(wallet))
        await self._session.flush()

    async def update(self, wallet: Wallet) -> None:
        row = await self._session.get(WalletRow, wallet.user_id)
        if row is None:
            raise LookupError(f"wallet for {wallet.user_id} does not exist")
        m.apply_wallet(row, wallet)
        await self._session.flush()

    async def get(self, user_id: UUID) -> Wallet | None:
        row = await self._session.get(WalletRow, user_id)
        return m.to_wallet(row) if row is not None else None

    async def get_for_update(self, user_id: UUID) -> Wallet | None:
        row = await self._session.scalar(
            select(WalletRow).where(WalletRow.user_id == user_id).with_for_update()
        )
        return m.to_wallet(row) if row is not None else None


class SqlAlchemyCreditLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: CreditLedgerEntry) -> None:
        self._session.add(m.new_ledger_row(entry))
        await self._session.flush()

    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int, kind: CreditKind | None = None
    ) -> tuple[list[CreditLedgerEntry], int]:
        criteria = [CreditLedgerRow.user_id == user_id]
        if kind is not None:
            criteria.append(CreditLedgerRow.kind == kind.value)
        total = await self._session.scalar(
            select(func.count()).select_from(CreditLedgerRow).where(*criteria)
        )
        rows = await self._session.scalars(
            select(CreditLedgerRow)
            .where(*criteria)
            .order_by(CreditLedgerRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [m.to_ledger_entry(row) for row in rows], int(total or 0)


class SqlAlchemyCreditPackageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, package: CreditPackage) -> None:
        self._session.add(
            CreditPackageRow(
                id=package.id,
                slug=package.slug,
                name=package.name,
                credits=package.credits,
                amount_minor=package.amount_minor,
                currency=package.currency,
                stripe_price_id=package.stripe_price_id,
                is_active=package.is_active,
                created_at=_now(),
            )
        )
        await self._session.flush()

    async def list_active(self) -> list[CreditPackage]:
        rows = await self._session.scalars(
            select(CreditPackageRow)
            .where(CreditPackageRow.is_active.is_(True))
            .order_by(CreditPackageRow.credits.asc())
        )
        return [m.to_credit_package(row) for row in rows]

    async def get(self, package_id: UUID) -> CreditPackage | None:
        row = await self._session.get(CreditPackageRow, package_id)
        return m.to_credit_package(row) if row is not None else None

    async def get_by_slug(self, slug: str) -> CreditPackage | None:
        row = await self._session.scalar(
            select(CreditPackageRow).where(CreditPackageRow.slug == slug)
        )
        return m.to_credit_package(row) if row is not None else None


class SqlAlchemyServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, service: Service) -> None:
        self._session.add(m.new_service_row(service))
        await self._session.flush()

    async def update(self, service: Service) -> None:
        row = await self._session.get(ServiceRow, service.id)
        if row is None:
            raise LookupError(f"service {service.id} does not exist")
        m.apply_service(row, service)
        await self._session.flush()

    async def get(self, service_id: UUID) -> Service | None:
        row = await self._session.get(ServiceRow, service_id)
        return m.to_service(row) if row is not None else None

    async def get_by_slug(self, slug: str) -> Service | None:
        row = await self._session.scalar(select(ServiceRow).where(ServiceRow.slug == slug))
        return m.to_service(row) if row is not None else None

    async def list(
        self, *, include_inactive: bool, limit: int, offset: int
    ) -> tuple[list[Service], int]:
        criteria = [] if include_inactive else [ServiceRow.is_active.is_(True)]
        total = await self._session.scalar(
            select(func.count()).select_from(ServiceRow).where(*criteria)
        )
        rows = await self._session.scalars(
            select(ServiceRow)
            .where(*criteria)
            .order_by(ServiceRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [m.to_service(row) for row in rows], int(total or 0)


class SqlAlchemyInvocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invocation: Invocation) -> None:
        self._session.add(m.new_invocation_row(invocation))
        await self._session.flush()

    async def update(self, invocation: Invocation) -> None:
        row = await self._session.get(InvocationRow, invocation.id)
        if row is None:
            raise LookupError(f"invocation {invocation.id} does not exist")
        m.apply_invocation(row, invocation)
        await self._session.flush()

    async def get(self, invocation_id: UUID) -> Invocation | None:
        row = await self._session.get(InvocationRow, invocation_id)
        return m.to_invocation(row) if row is not None else None

    async def get_by_idempotency_key(
        self, user_id: UUID, idempotency_key: str
    ) -> Invocation | None:
        row = await self._session.scalar(
            select(InvocationRow).where(
                InvocationRow.user_id == user_id,
                InvocationRow.idempotency_key == idempotency_key,
            )
        )
        return m.to_invocation(row) if row is not None else None

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        status: InvocationStatus | None = None,
        service_slug: str | None = None,
    ) -> tuple[list[Invocation], int]:
        criteria = self._criteria(user_id=user_id, status=status, service_slug=service_slug)
        return await self._page(criteria, limit=limit, offset=offset)

    async def list_all(
        self,
        *,
        limit: int,
        offset: int,
        user_id: UUID | None = None,
        status: InvocationStatus | None = None,
        service_slug: str | None = None,
    ) -> tuple[list[Invocation], int]:
        criteria = self._criteria(user_id=user_id, status=status, service_slug=service_slug)
        return await self._page(criteria, limit=limit, offset=offset)

    async def count_since(self, user_id: UUID, since: datetime) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(InvocationRow)
            .where(InvocationRow.user_id == user_id, InvocationRow.created_at >= since)
        )
        return int(total or 0)

    @staticmethod
    def _criteria(
        *,
        user_id: UUID | None,
        status: InvocationStatus | None,
        service_slug: str | None,
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = []
        if user_id is not None:
            criteria.append(InvocationRow.user_id == user_id)
        if status is not None:
            criteria.append(InvocationRow.status == status.value)
        if service_slug:
            criteria.append(InvocationRow.service_slug == service_slug)
        return criteria

    async def _page(
        self, criteria: list[ColumnElement[bool]], *, limit: int, offset: int
    ) -> tuple[list[Invocation], int]:
        total = await self._session.scalar(
            select(func.count()).select_from(InvocationRow).where(*criteria)
        )
        rows = await self._session.scalars(
            select(InvocationRow)
            .where(*criteria)
            .order_by(InvocationRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [m.to_invocation(row) for row in rows], int(total or 0)


class SqlAlchemyTopUpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, topup: TopUp) -> None:
        self._session.add(m.new_topup_row(topup))
        await self._session.flush()

    async def add_or_get(self, topup: TopUp) -> tuple[TopUp, bool]:
        result = await self._session.execute(
            pg_insert(TopUpRow)
            .values(
                id=topup.id,
                user_id=topup.user_id,
                package_id=topup.package_id,
                package_slug=topup.package_slug,
                credits=topup.credits,
                amount_minor=topup.amount_minor,
                currency=topup.currency,
                idempotency_key=topup.idempotency_key,
                status=topup.status.value,
                checkout_session_id=topup.checkout_session_id,
                checkout_url=topup.checkout_url,
                created_at=topup.created_at,
                updated_at=topup.updated_at,
            )
            .on_conflict_do_nothing(constraint="uq_topups_user_idempotency")
        )
        row = await self._session.scalar(
            select(TopUpRow).where(
                TopUpRow.user_id == topup.user_id,
                TopUpRow.idempotency_key == topup.idempotency_key,
            )
        )
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError("topup could not be persisted")
        return m.to_topup(row), _rowcount(result) == 1

    async def update(self, topup: TopUp) -> None:
        row = await self._session.get(TopUpRow, topup.id)
        if row is None:
            raise LookupError(f"topup {topup.id} does not exist")
        m.apply_topup(row, topup)
        await self._session.flush()

    async def get(self, topup_id: UUID) -> TopUp | None:
        row = await self._session.get(TopUpRow, topup_id)
        return m.to_topup(row) if row is not None else None

    async def get_by_idempotency_key(self, user_id: UUID, idempotency_key: str) -> TopUp | None:
        row = await self._session.scalar(
            select(TopUpRow).where(
                TopUpRow.user_id == user_id, TopUpRow.idempotency_key == idempotency_key
            )
        )
        return m.to_topup(row) if row is not None else None

    async def get_by_checkout_session(self, session_id: str) -> TopUp | None:
        row = await self._session.scalar(
            select(TopUpRow).where(TopUpRow.checkout_session_id == session_id)
        )
        return m.to_topup(row) if row is not None else None


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: RefreshToken) -> None:
        self._session.add(m.new_refresh_token_row(token))
        await self._session.flush()

    async def update(self, token: RefreshToken) -> None:
        row = await self._session.get(RefreshTokenRow, token.id)
        if row is None:
            raise LookupError(f"refresh token {token.id} does not exist")
        m.apply_refresh_token(row, token)
        await self._session.flush()

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        row = await self._session.scalar(
            select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_hash)
        )
        return m.to_refresh_token(row) if row is not None else None

    async def get(self, token_id: UUID) -> RefreshToken | None:
        row = await self._session.get(RefreshTokenRow, token_id)
        return m.to_refresh_token(row) if row is not None else None

    async def list_active_for_user(self, user_id: UUID, *, now: datetime) -> list[RefreshToken]:
        rows = await self._session.scalars(
            select(RefreshTokenRow)
            .where(
                RefreshTokenRow.user_id == user_id,
                RefreshTokenRow.revoked_at.is_(None),
                RefreshTokenRow.rotated_at.is_(None),
                RefreshTokenRow.expires_at > now,
            )
            .order_by(RefreshTokenRow.created_at.desc())
        )
        return [m.to_refresh_token(row) for row in rows]

    async def revoke_family(self, family_id: UUID, *, now: datetime) -> int:
        result = await self._session.execute(
            update(RefreshTokenRow)
            .where(RefreshTokenRow.family_id == family_id, RefreshTokenRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self._session.flush()
        return _rowcount(result)

    async def revoke_all_for_user(self, user_id: UUID, *, now: datetime) -> int:
        result = await self._session.execute(
            update(RefreshTokenRow)
            .where(RefreshTokenRow.user_id == user_id, RefreshTokenRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self._session.flush()
        return _rowcount(result)


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, api_key: ApiKey) -> None:
        self._session.add(m.new_api_key_row(api_key))
        await self._session.flush()

    async def update(self, api_key: ApiKey) -> None:
        row = await self._session.get(ApiKeyRow, api_key.id)
        if row is None:
            raise LookupError(f"api key {api_key.id} does not exist")
        m.apply_api_key(row, api_key)
        await self._session.flush()

    async def get(self, key_id: UUID) -> ApiKey | None:
        row = await self._session.get(ApiKeyRow, key_id)
        return m.to_api_key(row) if row is not None else None

    async def get_by_prefix(self, prefix: str) -> ApiKey | None:
        row = await self._session.scalar(select(ApiKeyRow).where(ApiKeyRow.prefix == prefix))
        return m.to_api_key(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[ApiKey]:
        rows = await self._session.scalars(
            select(ApiKeyRow)
            .where(ApiKeyRow.user_id == user_id)
            .order_by(ApiKeyRow.created_at.desc())
        )
        return [m.to_api_key(row) for row in rows]


class SqlAlchemyOneTimeTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: OneTimeToken) -> None:
        self._session.add(m.new_one_time_token_row(token))
        await self._session.flush()

    async def update(self, token: OneTimeToken) -> None:
        row = await self._session.get(OneTimeTokenRow, token.id)
        if row is None:
            raise LookupError(f"one time token {token.id} does not exist")
        m.apply_one_time_token(row, token)
        await self._session.flush()

    async def get_by_hash(self, token_hash: str) -> OneTimeToken | None:
        row = await self._session.scalar(
            select(OneTimeTokenRow).where(OneTimeTokenRow.token_hash == token_hash)
        )
        return m.to_one_time_token(row) if row is not None else None

    async def invalidate_active(self, user_id: UUID, kind: TokenKind, *, now: datetime) -> int:
        result = await self._session.execute(
            update(OneTimeTokenRow)
            .where(
                OneTimeTokenRow.user_id == user_id,
                OneTimeTokenRow.kind == kind.value,
                OneTimeTokenRow.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self._session.flush()
        return _rowcount(result)


class SqlAlchemyProcessedEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_if_new(
        self, *, event_id: str, event_type: str, reference: str | None = None
    ) -> bool:
        result = await self._session.execute(
            pg_insert(ProcessedStripeEventRow)
            .values(
                event_id=event_id,
                event_type=event_type,
                reference=reference,
                processed_at=_now(),
            )
            .on_conflict_do_nothing(index_elements=[ProcessedStripeEventRow.event_id])
        )
        await self._session.flush()
        return _rowcount(result) > 0


def _rowcount(result: object) -> int:
    """``Result`` does not always expose ``rowcount`` in SQLAlchemy's typing."""
    return int(getattr(result, "rowcount", 0) or 0)


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
