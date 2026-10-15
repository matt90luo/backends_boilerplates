"""Authentication and session use cases."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from tinysaas.application.dto.commands import (
    Credentials,
    LoginCommand,
    LogoutCommand,
    RefreshSessionCommand,
    RegisterUserCommand,
    RequestPasswordResetCommand,
    ResetPasswordCommand,
    VerifyEmailCommand,
)
from tinysaas.application.dto.identity import AuthSession, SessionView
from tinysaas.application.errors import (
    AuthenticationRequired,
    EmailAlreadyRegistered,
    EmailNotVerified,
    InvalidCredentials,
    InvalidToken,
    RefreshTokenReused,
    TokenExpired,
    UserDisabled,
    UserNotFound,
)
from tinysaas.application.options import AppOptions
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.external import EmailMessage, Mailer
from tinysaas.application.ports.observability import AppLogger
from tinysaas.application.ports.persistence import UnitOfWorkFactory
from tinysaas.application.ports.security import ApiKeyService, PasswordHasher, TokenService
from tinysaas.application.use_cases.tokens import OneTimeTokenIssuer, SessionIssuer
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.errors import DomainError, ValidationError
from tinysaas.domain.identity.one_time_token import TokenKind
from tinysaas.domain.identity.password import validate_password
from tinysaas.domain.identity.user import User, normalize_email


class RegisterUserUseCase:
    """Create the account, its wallet and an initial session."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        session_issuer: SessionIssuer,
        one_time_tokens: OneTimeTokenIssuer,
        mailer: Mailer,
        options: AppOptions,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._sessions = session_issuer
        self._one_time_tokens = one_time_tokens
        self._mailer = mailer
        self._options = options
        self._clock = clock
        self._logger = logger

    async def execute(self, command: RegisterUserCommand) -> AuthSession:
        now = self._clock.now()
        email = normalize_email(command.email)
        validate_password(command.password)

        async with self._uow_factory() as uow:
            if await uow.users.get_by_email(email) is not None:
                raise EmailAlreadyRegistered("该邮箱已注册", details={"field": "email"})
            user = User.register(
                email=email,
                password_hash=self._password_hasher.hash(command.password),
                display_name=command.display_name,
                now=now,
            )
            await uow.users.add(user)
            await uow.wallets.add(Wallet.for_user(user.id, now=now))
            verification_token = await self._one_time_tokens.issue(
                uow, user=user, kind=TokenKind.EMAIL_VERIFICATION
            )
            session = await self._sessions.issue(
                uow,
                user=user,
                user_agent=command.user_agent,
                ip_address=command.ip_address,
            )
            await uow.commit()

        await self._send_welcome(user, verification_token)
        self._logger.info("user_registered", user_id=str(user.id))
        return session

    async def _send_welcome(self, user: User, verification_token: str) -> None:
        options = self._options
        display_name = user.display_name or user.email
        link = options.session.verify_email_url(verification_token)
        messages = [
            EmailMessage(
                to=user.email,
                subject=f"欢迎加入 {options.notification.app_name}",
                template="welcome",
                context={
                    "app_name": options.notification.app_name,
                    "display_name": display_name,
                    "support_email": options.notification.support_email,
                    "verify_url": link,
                },
            ),
            EmailMessage(
                to=user.email,
                subject=f"请验证你的邮箱 · {options.notification.app_name}",
                template="verify_email",
                context={
                    "app_name": options.notification.app_name,
                    "display_name": display_name,
                    "support_email": options.notification.support_email,
                    "verify_url": link,
                },
            ),
        ]
        for message in messages:
            try:
                await self._mailer.send(message)
            except Exception as error:  # pragma: no cover - delivery is best effort
                self._logger.warning(
                    "email_delivery_failed",
                    template=message.template,
                    user_id=str(user.id),
                    error=str(error),
                )


class LoginUseCase:
    """Verify credentials and open a new session."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        session_issuer: SessionIssuer,
        options: AppOptions,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._sessions = session_issuer
        self._options = options
        self._clock = clock
        self._logger = logger
        self._dummy_hash = password_hasher.hash("tinysaas-timing-equalizer")

    async def execute(self, command: LoginCommand) -> AuthSession:
        email = normalize_email(command.email)
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)
            if user is None:
                self._password_hasher.verify(self._dummy_hash, command.password)
                raise InvalidCredentials("邮箱或密码不正确")
            if not self._password_hasher.verify(user.password_hash, command.password):
                raise InvalidCredentials("邮箱或密码不正确")
            if not user.is_active:
                raise UserDisabled("账号已被禁用")
            if self._options.session.require_email_verification and not user.is_email_verified:
                raise EmailNotVerified("请先完成邮箱验证")
            session = await self._sessions.issue(
                uow,
                user=user,
                user_agent=command.user_agent,
                ip_address=command.ip_address,
            )
            await uow.commit()
        self._logger.info("user_logged_in", user_id=str(user.id))
        return session


class RefreshSessionUseCase:
    """Rotate a refresh token; replaying an old one kills the whole family."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        token_service: TokenService,
        session_issuer: SessionIssuer,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._token_service = token_service
        self._sessions = session_issuer
        self._clock = clock
        self._logger = logger

    async def execute(self, command: RefreshSessionCommand) -> AuthSession:
        now = self._clock.now()
        token_hash = self._token_service.hash_token(command.refresh_token)
        async with self._uow_factory() as uow:
            record = await uow.refresh_tokens.get_by_hash(token_hash)
            if record is None:
                raise InvalidToken("refresh token 无效")
            if record.is_rotated or record.is_revoked:
                await uow.refresh_tokens.revoke_family(record.family_id, now=now)
                await uow.commit()
                self._logger.warning(
                    "refresh_token_reuse_detected",
                    user_id=str(record.user_id),
                    family_id=str(record.family_id),
                )
                raise RefreshTokenReused("检测到 refresh token 重复使用，该会话已全部注销")
            if record.expires_at <= now:
                raise TokenExpired("refresh token 已过期")
            user = await uow.users.get(record.user_id)
            if user is None:
                raise InvalidToken("refresh token 无效")
            if not user.is_active:
                raise UserDisabled("账号已被禁用")
            record.rotate(now=now)
            await uow.refresh_tokens.update(record)
            session = await self._sessions.issue(
                uow,
                user=user,
                user_agent=command.user_agent or record.user_agent,
                ip_address=record.ip_address,
                family_id=record.family_id,
            )
            await uow.commit()
        return session


class LogoutUseCase:
    def __init__(
        self, *, uow_factory: UnitOfWorkFactory, token_service: TokenService, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._token_service = token_service
        self._clock = clock

    async def execute(self, command: LogoutCommand) -> None:
        now = self._clock.now()
        token_hash = self._token_service.hash_token(command.refresh_token)
        async with self._uow_factory() as uow:
            record = await uow.refresh_tokens.get_by_hash(token_hash)
            if record is None:
                return
            record.revoke(now=now)
            await uow.refresh_tokens.update(record)
            await uow.commit()


class LogoutAllUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal) -> int:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            revoked = await uow.refresh_tokens.revoke_all_for_user(principal.user_id, now=now)
            await uow.commit()
        return revoked


class RevokeSessionUseCase:
    """Revoke one of the caller's own sessions (``DELETE /auth/sessions/{id}``)."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal, session_id: UUID) -> None:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            record = await uow.refresh_tokens.get(session_id)
            if record is None or record.user_id != principal.user_id:
                raise InvalidToken("会话不存在")
            record.revoke(now=now)
            await uow.refresh_tokens.update(record)
            await uow.commit()


class ListSessionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal) -> list[SessionView]:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            tokens = await uow.refresh_tokens.list_active_for_user(principal.user_id, now=now)
        return [SessionView.from_token(token) for token in tokens]


class AuthenticateRequestUseCase:
    """Resolve raw credentials into a :class:`Principal` (or ``None``).

    Called from the auth middleware, so it must never raise for bad
    credentials: an invalid token simply yields ``None`` and the route level
    dependency decides between 401 and anonymous access.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        token_service: TokenService,
        api_key_service: ApiKeyService,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._token_service = token_service
        self._api_key_service = api_key_service
        self._clock = clock
        self._logger = logger

    async def execute(self, credentials: Credentials) -> Principal | None:
        if credentials.scheme == "bearer":
            return await self._from_bearer(credentials)
        if credentials.scheme == "api_key":
            return await self._from_api_key(credentials)
        return None

    async def _from_bearer(self, credentials: Credentials) -> Principal | None:
        try:
            claims = self._token_service.decode_access_token(credentials.value)
        except DomainError as error:
            self._logger.info("access_token_rejected", code=error.code)
            return None
        async with self._uow_factory() as uow:
            user = await uow.users.get(claims.user_id)
        if user is None or not user.is_active:
            return None
        return _principal(user)

    async def _from_api_key(self, credentials: Credentials) -> Principal | None:
        now = self._clock.now()
        prefix = self._api_key_service.prefix_of(credentials.value)
        async with self._uow_factory() as uow:
            api_key = await uow.api_keys.get_by_prefix(prefix)
            if api_key is None or not self._api_key_service.verify(
                api_key.key_hash, credentials.value
            ):
                self._logger.info("api_key_rejected", reason="unknown")
                return None
            if not api_key.is_usable(now=now):
                self._logger.info("api_key_rejected", reason="expired_or_revoked")
                return None
            user = await uow.users.get(api_key.user_id)
            if user is None or not user.is_active:
                return None
            if self._should_touch(api_key.last_used_at, now):
                api_key.touch(now=now)
                await uow.api_keys.update(api_key)
                await uow.commit()
        return _principal(user)

    @staticmethod
    def _should_touch(last_used_at: datetime | None, now: datetime) -> bool:
        if last_used_at is None:
            return True
        return (now - last_used_at).total_seconds() > 300


def _principal(user: User) -> Principal:
    return Principal(
        user_id=user.id,
        role=user.role,
        plan=user.plan,
        daily_quota=user.daily_quota,
    )


class VerifyEmailUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        token_service: TokenService,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._token_service = token_service
        self._clock = clock

    async def execute(self, command: VerifyEmailCommand) -> None:
        now = self._clock.now()
        token_hash = self._token_service.hash_token(command.token)
        async with self._uow_factory() as uow:
            token = await uow.one_time_tokens.get_by_hash(token_hash)
            if (
                token is None
                or token.kind is not TokenKind.EMAIL_VERIFICATION
                or not token.is_usable(now=now)
            ):
                raise InvalidToken("验证链接无效或已过期")
            user = await uow.users.get(token.user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            user.mark_email_verified(now=now)
            token.consume(now=now)
            await uow.users.update(user)
            await uow.one_time_tokens.update(token)
            await uow.commit()


class RequestPasswordResetUseCase:
    """Always succeeds so that the endpoint cannot enumerate accounts."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        one_time_tokens: OneTimeTokenIssuer,
        mailer: Mailer,
        options: AppOptions,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._one_time_tokens = one_time_tokens
        self._mailer = mailer
        self._options = options
        self._clock = clock
        self._logger = logger

    async def execute(self, command: RequestPasswordResetCommand) -> None:
        try:
            email = normalize_email(command.email)
        except ValidationError:
            return
        now = self._clock.now()
        reset_token: str | None = None
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)
            if user is None or not user.is_active:
                return
            await uow.one_time_tokens.invalidate_active(user.id, TokenKind.PASSWORD_RESET, now=now)
            reset_token = await self._one_time_tokens.issue(
                uow, user=user, kind=TokenKind.PASSWORD_RESET
            )
            await uow.commit()
        link = self._options.session.reset_password_url(reset_token)
        try:
            await self._mailer.send(
                EmailMessage(
                    to=email,
                    subject=f"重置密码 · {self._options.notification.app_name}",
                    template="password_reset",
                    context={
                        "app_name": self._options.notification.app_name,
                        "display_name": user.display_name or user.email,
                        "support_email": self._options.notification.support_email,
                        "reset_url": link,
                        "expires_in_minutes": self._options.session.password_reset_ttl_seconds
                        // 60,
                    },
                )
            )
        except Exception as error:  # pragma: no cover - delivery is best effort
            self._logger.warning(
                "email_delivery_failed", template="password_reset", error=str(error)
            )


class ResetPasswordUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._clock = clock

    async def execute(self, command: ResetPasswordCommand) -> None:
        validate_password(command.new_password)
        now = self._clock.now()
        token_hash = self._token_service.hash_token(command.token)
        async with self._uow_factory() as uow:
            token = await uow.one_time_tokens.get_by_hash(token_hash)
            if (
                token is None
                or token.kind is not TokenKind.PASSWORD_RESET
                or not token.is_usable(now=now)
            ):
                raise InvalidToken("重置链接无效或已过期")
            user = await uow.users.get(token.user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            user.change_password_hash(self._password_hasher.hash(command.new_password), now=now)
            token.consume(now=now)
            await uow.users.update(user)
            await uow.one_time_tokens.update(token)
            await uow.refresh_tokens.revoke_all_for_user(user.id, now=now)
            await uow.commit()


def ensure_principal(principal: Principal | None) -> Principal:
    """Used by route dependencies to turn ``None`` into a 401."""
    if principal is None:
        raise AuthenticationRequired("需要登录")
    return principal
