"""User aggregate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from tinysaas.domain.errors import Forbidden, ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_DAILY_QUOTA = 1_000_000


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"


DEFAULT_DAILY_QUOTA: dict[Plan, int] = {Plan.FREE: 20, Plan.PRO: 1000}


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    """Normalize and validate an email address."""
    candidate = email.strip().lower()
    if not _EMAIL_RE.match(candidate):
        raise ValidationError("邮箱格式不正确", details={"field": "email"})
    return candidate


@dataclass
class User:
    """A registered account with a global role inside the SaaS."""

    id: UUID
    email: str
    password_hash: str
    role: Role = Role.USER
    plan: Plan = Plan.FREE
    daily_quota: int = DEFAULT_DAILY_QUOTA[Plan.FREE]
    is_active: bool = True
    display_name: str | None = None
    avatar_key: str | None = None
    email_verified_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def register(
        cls,
        *,
        email: str,
        password_hash: str,
        role: Role = Role.USER,
        plan: Plan = Plan.FREE,
        daily_quota: int | None = None,
        display_name: str | None = None,
        now: datetime | None = None,
    ) -> User:
        if not password_hash:
            raise ValidationError("密码哈希不能为空", details={"field": "password_hash"})
        quota = DEFAULT_DAILY_QUOTA[plan] if daily_quota is None else daily_quota
        cls._validate_quota(quota)
        moment = now or _now()
        return cls(
            id=uuid4(),
            email=normalize_email(email),
            password_hash=password_hash,
            role=role,
            plan=plan,
            daily_quota=quota,
            display_name=display_name,
            created_at=moment,
            updated_at=moment,
        )

    @staticmethod
    def _validate_quota(quota: int) -> None:
        if quota < 0 or quota > _MAX_DAILY_QUOTA:
            raise ValidationError(
                f"每日配额必须在 0 到 {_MAX_DAILY_QUOTA} 之间", details={"field": "daily_quota"}
            )

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    def mark_email_verified(self, *, now: datetime | None = None) -> None:
        if self.email_verified_at is None:
            self.email_verified_at = now or _now()
            self._touch(now)

    def change_password_hash(self, password_hash: str, *, now: datetime | None = None) -> None:
        if not password_hash:
            raise ValidationError("密码哈希不能为空", details={"field": "password_hash"})
        self.password_hash = password_hash
        self._touch(now)

    def update_profile(
        self,
        *,
        display_name: str | None = None,
        avatar_key: str | None = None,
        now: datetime | None = None,
    ) -> None:
        if display_name is not None:
            cleaned = display_name.strip()
            if len(cleaned) > 80:
                raise ValidationError("昵称不能超过 80 个字符", details={"field": "display_name"})
            self.display_name = cleaned or None
        if avatar_key is not None:
            self.avatar_key = avatar_key or None
        self._touch(now)

    def apply_admin_update(
        self,
        *,
        actor_id: UUID,
        role: Role | None = None,
        plan: Plan | None = None,
        daily_quota: int | None = None,
        is_active: bool | None = None,
        now: datetime | None = None,
    ) -> None:
        """Apply an administrative change; administrators cannot lock themselves out."""
        if role is not None and role is not self.role:
            if actor_id == self.id:
                raise Forbidden("不能修改自己的角色", details={"field": "role"})
            self.role = role
        if plan is not None and plan is not self.plan:
            self.plan = plan
            if daily_quota is None:
                daily_quota = DEFAULT_DAILY_QUOTA[plan]
        if daily_quota is not None:
            self._validate_quota(daily_quota)
            self.daily_quota = daily_quota
        if is_active is not None and is_active != self.is_active:
            if not is_active and actor_id == self.id:
                raise Forbidden("不能禁用当前登录的管理员账号", details={"field": "is_active"})
            self.is_active = is_active
        self._touch(now)

    def _touch(self, now: datetime | None = None) -> None:
        self.updated_at = now or _now()
