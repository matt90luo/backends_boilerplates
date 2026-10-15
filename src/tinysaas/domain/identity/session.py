"""Refresh token (server side session) aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from tinysaas.domain.errors import ValidationError


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RefreshToken:
    """A hashed, rotating refresh token belonging to a token family.

    Rotating a token issues a new token in the same ``family_id``; replaying a
    rotated token is treated as theft and revokes the whole family.
    """

    id: UUID
    user_id: UUID
    token_hash: str
    family_id: UUID
    expires_at: datetime
    created_at: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def issue(
        cls,
        *,
        user_id: UUID,
        token_hash: str,
        ttl: timedelta,
        family_id: UUID | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> RefreshToken:
        if not token_hash:
            raise ValidationError("refresh token 哈希不能为空", details={"field": "token_hash"})
        if ttl.total_seconds() <= 0:
            raise ValidationError("refresh token 有效期必须大于 0", details={"field": "ttl"})
        moment = now or _now()
        return cls(
            id=uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id or uuid4(),
            expires_at=moment + ttl,
            created_at=moment,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_rotated(self) -> bool:
        return self.rotated_at is not None

    def is_active(self, *, now: datetime | None = None) -> bool:
        moment = now or _now()
        return not self.is_revoked and not self.is_rotated and self.expires_at > moment

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= _now()

    def rotate(self, *, now: datetime | None = None) -> None:
        if not self.is_active(now=now):
            raise ValidationError("该会话已失效", details={"field": "refresh_token"})
        self.rotated_at = now or _now()

    def revoke(self, *, now: datetime | None = None) -> None:
        self.revoked_at = now or _now()
