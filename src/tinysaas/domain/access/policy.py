"""RBAC: who may do what.

The acting identity is modelled as a :class:`Principal` value object so that
authorisation can be evaluated inside the domain without touching the ORM.
``org_id`` is the multi tenancy seam: today it is always ``None``, but every
repository query is already scoped by a principal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from tinysaas.domain.catalog.service import Service, ServiceInactive
from tinysaas.domain.errors import Forbidden
from tinysaas.domain.identity.user import Plan, Role


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated actor behind a request."""

    user_id: UUID
    role: Role
    plan: Plan
    daily_quota: int
    org_id: UUID | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


class AccessPolicy:
    """Pure authorisation rules (no I/O)."""

    @staticmethod
    def ensure_admin(principal: Principal) -> None:
        if not principal.is_admin:
            raise Forbidden("需要管理员权限")

    @staticmethod
    def ensure_can_manage_users(principal: Principal) -> None:
        AccessPolicy.ensure_admin(principal)

    @staticmethod
    def can_view_invocation(principal: Principal, owner_id: UUID) -> bool:
        return principal.is_admin or principal.user_id == owner_id

    @staticmethod
    def ensure_can_view_invocation(principal: Principal, owner_id: UUID) -> None:
        if not AccessPolicy.can_view_invocation(principal, owner_id):
            raise Forbidden("无权访问该调用日志")

    @staticmethod
    def ensure_can_invoke(principal: Principal, service: Service) -> None:
        if not service.is_active:
            raise ServiceInactive("服务未上线", details={"service_slug": service.slug})
