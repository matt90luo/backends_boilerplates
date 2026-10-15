"""JWT access tokens plus opaque token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from tinysaas.application.errors import InvalidToken, TokenExpired
from tinysaas.application.ports.security import AccessClaims
from tinysaas.domain.identity.user import Role

_OPAQUE_TOKEN_BYTES = 32


class PyJWTTokenService:
    """Adapter implementing :class:`TokenService`."""

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: str = "tinysaas",
        audience: str = "tinysaas-clients",
        access_token_ttl_seconds: int = 900,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._ttl = access_token_ttl_seconds

    def create_access_token(
        self, *, user_id: UUID, role: Role, now: datetime | None = None
    ) -> tuple[str, int]:
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=self._ttl)
        payload = {
            "sub": str(user_id),
            "role": role.value,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_hex(8),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        return token, self._ttl

    def decode_access_token(self, token: str) -> AccessClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "sub"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise TokenExpired("access token 已过期") from error
        except jwt.PyJWTError as error:
            raise InvalidToken("access token 无效") from error

        subject = payload.get("sub")
        role = payload.get("role", Role.USER.value)
        expires_at = payload.get("exp")
        if not isinstance(expires_at, int):
            raise InvalidToken("access token 载荷无效")
        try:
            user_id = UUID(str(subject))
            parsed_expiry = datetime.fromtimestamp(expires_at, tz=UTC)
            parsed_role = Role(str(role))
        except (TypeError, ValueError) as error:
            raise InvalidToken("access token 载荷无效") from error
        return AccessClaims(user_id=user_id, role=parsed_role, expires_at=parsed_expiry)

    def new_opaque_token(self) -> str:
        return secrets.token_urlsafe(_OPAQUE_TOKEN_BYTES)

    def hash_token(self, token: str) -> str:
        """Deterministic digest (HMAC-SHA256) so tokens are never stored raw."""
        return hmac.new(
            self._secret_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
        ).hexdigest()
