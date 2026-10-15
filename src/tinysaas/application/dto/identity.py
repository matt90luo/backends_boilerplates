"""Identity DTOs (request results shown to clients)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tinysaas.domain.identity.api_key import ApiKey
from tinysaas.domain.identity.session import RefreshToken
from tinysaas.domain.identity.user import Plan, Role, User


@dataclass(frozen=True, slots=True)
class UserView:
    id: UUID
    email: str
    role: Role
    plan: Plan
    daily_quota: int
    is_active: bool
    display_name: str | None
    avatar_key: str | None
    email_verified: bool
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserView:
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            plan=user.plan,
            daily_quota=user.daily_quota,
            is_active=user.is_active,
            display_name=user.display_name,
            avatar_key=user.avatar_key,
            email_verified=user.is_email_verified,
            created_at=user.created_at,
        )


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Tokens handed to the client after register/login/refresh."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    user: UserView


@dataclass(frozen=True, slots=True)
class SessionView:
    id: UUID
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None

    @classmethod
    def from_token(cls, token: RefreshToken) -> SessionView:
        return cls(
            id=token.id,
            created_at=token.created_at,
            expires_at=token.expires_at,
            user_agent=token.user_agent,
            ip_address=token.ip_address,
        )


@dataclass(frozen=True, slots=True)
class ApiKeyView:
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked: bool

    @classmethod
    def from_api_key(cls, api_key: ApiKey) -> ApiKeyView:
        return cls(
            id=api_key.id,
            name=api_key.name,
            prefix=api_key.prefix,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            expires_at=api_key.expires_at,
            revoked=api_key.is_revoked,
        )


@dataclass(frozen=True, slots=True)
class ApiKeyIssued:
    """Returned exactly once: the plaintext key is never stored."""

    api_key: ApiKeyView
    plaintext: str
