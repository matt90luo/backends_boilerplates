"""Ports for password hashing, token issuing and API key material."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from tinysaas.domain.identity.user import Role


@dataclass(frozen=True, slots=True)
class AccessClaims:
    """Decoded access token payload."""

    user_id: UUID
    role: Role
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ApiKeyMaterial:
    """A freshly generated API key: the plaintext is shown to the user once."""

    plaintext: str
    prefix: str
    key_hash: str


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


class TokenService(Protocol):
    def create_access_token(
        self, *, user_id: UUID, role: Role, now: datetime | None = None
    ) -> tuple[str, int]:
        """Return ``(token, expires_in_seconds)``."""
        ...

    def decode_access_token(self, token: str) -> AccessClaims: ...

    def new_opaque_token(self) -> str:
        """Random URL safe token used for refresh tokens and one time links."""
        ...

    def hash_token(self, token: str) -> str:
        """Deterministic digest used to store tokens at rest."""
        ...


class ApiKeyService(Protocol):
    def generate(self) -> ApiKeyMaterial: ...

    def hash(self, plaintext: str) -> str: ...

    def prefix_of(self, plaintext: str) -> str: ...

    def verify(self, key_hash: str, plaintext: str) -> bool: ...
