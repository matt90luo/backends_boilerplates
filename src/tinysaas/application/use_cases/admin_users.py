"""Administrator user management use cases."""

from __future__ import annotations

from uuid import UUID

from tinysaas.application.dto.admin import AdminUserView
from tinysaas.application.dto.commands import ListUsersQuery, UpdateUserCommand
from tinysaas.application.dto.common import Page
from tinysaas.application.dto.identity import UserView
from tinysaas.application.errors import UserNotFound
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.persistence import UnitOfWorkFactory
from tinysaas.domain.access.policy import AccessPolicy, Principal
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.identity.user import User

DEFAULT_LIMIT = 50


class ListUsersUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal, query: ListUsersQuery) -> Page[AdminUserView]:
        AccessPolicy.ensure_admin(principal)
        async with self._uow_factory() as uow:
            users, total = await uow.users.list(
                limit=query.limit, offset=query.offset, search=query.search
            )
            views: list[AdminUserView] = []
            for user in users:
                wallet = await uow.wallets.get(user.id)
                views.append(_to_admin_view(user, wallet))
        return Page(items=views, total=total, limit=query.limit, offset=query.offset)


class GetUserUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, user_id: UUID) -> AdminUserView:
        AccessPolicy.ensure_admin(principal)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            wallet = await uow.wallets.get(user_id)
        return _to_admin_view(user, wallet)


class UpdateUserUseCase:
    """Role, plan, quota and activation changes (never self destructive)."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, principal: Principal, user_id: UUID, command: UpdateUserCommand
    ) -> AdminUserView:
        AccessPolicy.ensure_admin(principal)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            user.apply_admin_update(
                actor_id=principal.user_id,
                role=command.role,
                plan=command.plan,
                daily_quota=command.daily_quota,
                is_active=command.is_active,
                now=self._clock.now(),
            )
            await uow.users.update(user)
            wallet = await uow.wallets.get(user_id)
            await uow.commit()
        return _to_admin_view(user, wallet)


def _to_admin_view(user: User, wallet: Wallet | None) -> AdminUserView:
    return AdminUserView(
        user=UserView.from_user(user),
        balance=wallet.balance if wallet else 0,
        reserved=wallet.reserved if wallet else 0,
    )
