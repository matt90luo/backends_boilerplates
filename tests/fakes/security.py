"""Deterministic stand-ins for hashing / token issuing."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from tinysaas.application.errors import InvalidToken, TokenExpired
from tinysaas.application.ports.security import AccessClaims, ApiKeyMaterial
from tinysaas.domain.identity.user import Role


class FakePasswordHasher:
    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"hashed::{password}"


class FakeTokenService:
    """Access tokens are ``access.<user_id>.<role>.<exp>`` strings."""

    def __init__(
        self,
        *,
        access_token_ttl_seconds: int = 900,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl = access_token_ttl_seconds
        self._clock = clock
        self._counter = itertools.count(1)

    def _now(self) -> datetime:
        return self._clock() if self._clock else datetime.now(UTC)

    def create_access_token(
        self, *, user_id: UUID, role: Role, now: datetime | None = None
    ) -> tuple[str, int]:
        issued_at = now or self._now()
        expires_at = issued_at + timedelta(seconds=self._ttl)
        token = f"access.{user_id}.{role.value}.{int(expires_at.timestamp())}.{next(self._counter)}"
        return token, self._ttl

    def decode_access_token(self, token: str) -> AccessClaims:
        parts = token.split(".")
        if len(parts) != 5 or parts[0] != "access":
            raise InvalidToken("access token 无效")
        try:
            user_id = UUID(parts[1])
            role = Role(parts[2])
            expires_at = datetime.fromtimestamp(int(parts[3]), tz=UTC)
        except ValueError as error:
            raise InvalidToken("access token 无效") from error
        if expires_at <= self._now():
            raise TokenExpired("access token 已过期")
        return AccessClaims(user_id=user_id, role=role, expires_at=expires_at)

    def new_opaque_token(self) -> str:
        return f"opaque-{next(self._counter)}"

    def hash_token(self, token: str) -> str:
        return f"digest::{token}"


class FakeApiKeyService:
    def __init__(self, *, prefix: str = "tsk") -> None:
        self._prefix = prefix
        self._counter = itertools.count(1)

    def generate(self) -> ApiKeyMaterial:
        index = next(self._counter)
        lookup = f"{index:08x}"
        plaintext = f"{self._prefix}_{lookup}_secret{index}"
        return ApiKeyMaterial(plaintext=plaintext, prefix=lookup, key_hash=self.hash(plaintext))

    def hash(self, plaintext: str) -> str:
        return f"apikey::{plaintext}"

    def prefix_of(self, plaintext: str) -> str:
        parts = plaintext.split("_")
        return parts[1] if len(parts) == 3 else ""

    def verify(self, key_hash: str, plaintext: str) -> bool:
        return key_hash == self.hash(plaintext)
