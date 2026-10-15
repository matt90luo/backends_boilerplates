"""Collaborators that mint credentials for the auth use cases."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from tinysaas.application.dto.identity import AuthSession, UserView
from tinysaas.application.options import AppOptions
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.persistence import UnitOfWork
from tinysaas.application.ports.security import TokenService
from tinysaas.domain.identity.one_time_token import OneTimeToken, TokenKind
from tinysaas.domain.identity.session import RefreshToken
from tinysaas.domain.identity.user import User


class SessionIssuer:
    """Creates an access token plus a rotating, hashed refresh token."""

    def __init__(self, *, token_service: TokenService, clock: Clock, options: AppOptions) -> None:
        self._token_service = token_service
        self._clock = clock
        self._options = options

    async def issue(
        self,
        uow: UnitOfWork,
        *,
        user: User,
        user_agent: str | None = None,
        ip_address: str | None = None,
        family_id: UUID | None = None,
    ) -> AuthSession:
        now = self._clock.now()
        ttl = timedelta(seconds=self._options.session.refresh_token_ttl_seconds)
        plaintext = self._token_service.new_opaque_token()
        record = RefreshToken.issue(
            user_id=user.id,
            token_hash=self._token_service.hash_token(plaintext),
            ttl=ttl,
            family_id=family_id,
            user_agent=user_agent,
            ip_address=ip_address,
            now=now,
        )
        await uow.refresh_tokens.add(record)
        access_token, expires_in = self._token_service.create_access_token(
            user_id=user.id, role=user.role, now=now
        )
        return AuthSession(
            access_token=access_token,
            refresh_token=plaintext,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_expires_in=int(ttl.total_seconds()),
            user=UserView.from_user(user),
        )


class OneTimeTokenIssuer:
    """Issues single use links (email verification, password reset)."""

    def __init__(self, *, token_service: TokenService, clock: Clock, options: AppOptions) -> None:
        self._token_service = token_service
        self._clock = clock
        self._options = options

    def _ttl(self, kind: TokenKind) -> timedelta:
        session = self._options.session
        if kind is TokenKind.EMAIL_VERIFICATION:
            return timedelta(seconds=session.email_verification_ttl_seconds)
        return timedelta(seconds=session.password_reset_ttl_seconds)

    async def issue(self, uow: UnitOfWork, *, user: User, kind: TokenKind) -> str:
        now = self._clock.now()
        plaintext = self._token_service.new_opaque_token()
        token = OneTimeToken.issue(
            user_id=user.id,
            kind=kind,
            token_hash=self._token_service.hash_token(plaintext),
            ttl=self._ttl(kind),
            now=now,
        )
        await uow.one_time_tokens.add(token)
        return plaintext
