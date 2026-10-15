"""API key aggregate for machine to machine access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from tinysaas.domain.errors import ValidationError


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ApiKey:
    """A long lived credential. Only the hash is stored."""

    id: UUID
    user_id: UUID
    name: str
    prefix: str
    key_hash: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def issue(
        cls,
        *,
        user_id: UUID,
        name: str,
        prefix: str,
        key_hash: str,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> ApiKey:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("API Key 名称不能为空", details={"field": "name"})
        if len(cleaned) > 60:
            raise ValidationError("API Key 名称不能超过 60 个字符", details={"field": "name"})
        if not prefix or not key_hash:
            raise ValidationError("API Key 生成失败", details={"field": "key"})
        moment = now or _now()
        return cls(
            id=uuid4(),
            user_id=user_id,
            name=cleaned,
            prefix=prefix,
            key_hash=key_hash,
            created_at=moment,
            expires_at=moment + ttl if ttl else None,
        )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_usable(self, *, now: datetime | None = None) -> bool:
        moment = now or _now()
        if self.is_revoked:
            return False
        return self.expires_at is None or self.expires_at > moment

    def revoke(self, *, now: datetime | None = None) -> None:
        self.revoked_at = now or _now()

    def touch(self, *, now: datetime | None = None) -> None:
        self.last_used_at = now or _now()
