"""Single use tokens: email verification and password reset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from tinysaas.domain.errors import ValidationError


class TokenKind(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class OneTimeToken:
    id: UUID
    user_id: UUID
    kind: TokenKind
    token_hash: str
    expires_at: datetime
    created_at: datetime
    used_at: datetime | None = None

    @classmethod
    def issue(
        cls,
        *,
        user_id: UUID,
        kind: TokenKind,
        token_hash: str,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> OneTimeToken:
        if not token_hash:
            raise ValidationError("令牌生成失败", details={"field": "token"})
        if ttl.total_seconds() <= 0:
            raise ValidationError("令牌有效期必须大于 0", details={"field": "ttl"})
        moment = now or _now()
        return cls(
            id=uuid4(),
            user_id=user_id,
            kind=kind,
            token_hash=token_hash,
            expires_at=moment + ttl,
            created_at=moment,
        )

    def is_usable(self, *, now: datetime | None = None) -> bool:
        moment = now or _now()
        return self.used_at is None and self.expires_at > moment

    def consume(self, *, now: datetime | None = None) -> None:
        self.used_at = now or _now()
