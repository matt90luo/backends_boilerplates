"""The composition root.

``Container`` is the only module that knows both the application use cases and
the concrete adapters. It wires the routers (``@inject`` + ``Provide[...]``) and
owns the process-wide resources.

Dependency direction: ``containers -> adapters / infrastructure / application / domain``.
"""

from __future__ import annotations

from dependency_injector import containers, providers

from tinysaas.adapters.executors.composite import CompositeServiceExecutor
from tinysaas.adapters.executors.http_proxy import HttpProxyServiceExecutor
from tinysaas.adapters.executors.inprocess import (
    InProcessServiceExecutor,
    build_demo_handlers,
)
from tinysaas.adapters.mail.console import ConsoleMailer
from tinysaas.adapters.mail.renderer import TemplateRenderer
from tinysaas.adapters.mail.resend import ResendMailer
from tinysaas.adapters.observability.sentry import SentryTelemetry, init_sentry
from tinysaas.adapters.payments.stripe_gateway import StripePaymentGateway
from tinysaas.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from tinysaas.adapters.queue.arq_queue import ArqTaskQueue
from tinysaas.adapters.ratelimit.redis_limiter import RedisRateLimiter
from tinysaas.adapters.security.api_keys import HashedApiKeyService
from tinysaas.adapters.security.password import Argon2PasswordHasher
from tinysaas.adapters.security.tokens import PyJWTTokenService
from tinysaas.adapters.storage.memory import InMemoryObjectStorage
from tinysaas.adapters.storage.s3_storage import S3ObjectStorage
from tinysaas.adapters.web.cookies import build_cookie_policy
from tinysaas.application.options import AppOptions
from tinysaas.application.use_cases.admin_users import (
    GetUserUseCase,
    ListUsersUseCase,
    UpdateUserUseCase,
)
from tinysaas.application.use_cases.api_keys import (
    CreateApiKeyUseCase,
    ListApiKeysUseCase,
    RevokeApiKeyUseCase,
)
from tinysaas.application.use_cases.auth import (
    AuthenticateRequestUseCase,
    ListSessionsUseCase,
    LoginUseCase,
    LogoutAllUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
    RegisterUserUseCase,
    RequestPasswordResetUseCase,
    ResetPasswordUseCase,
    RevokeSessionUseCase,
    VerifyEmailUseCase,
)
from tinysaas.application.use_cases.billing import (
    GetTopUpUseCase,
    GetWalletUseCase,
    GrantCreditsUseCase,
    HandleTopUpWebhookUseCase,
    ListCreditPackagesUseCase,
    ListLedgerUseCase,
    StartTopUpUseCase,
)
from tinysaas.application.use_cases.catalog import (
    CreateServiceUseCase,
    DeactivateServiceUseCase,
    GetServiceUseCase,
    ListServicesUseCase,
    UpdateServiceUseCase,
)
from tinysaas.application.use_cases.files import PresignDownloadUseCase, PresignUploadUseCase
from tinysaas.application.use_cases.invocations import (
    ExecuteServiceUseCase,
    GetInvocationUseCase,
    GetTaskUseCase,
    InvocationSettlement,
    ListAllInvocationsUseCase,
    ListMyInvocationsUseCase,
    RunServiceTaskUseCase,
    SubmitServiceTaskUseCase,
)
from tinysaas.application.use_cases.profile import (
    ChangePasswordUseCase,
    GetProfileUseCase,
    UpdateProfileUseCase,
)
from tinysaas.application.use_cases.readiness import CheckReadinessUseCase
from tinysaas.application.use_cases.tokens import OneTimeTokenIssuer, SessionIssuer
from tinysaas.domain.billing.service import CreditReservationService
from tinysaas.infrastructure.clock import SystemClock, UuidGenerator
from tinysaas.infrastructure.config import Settings, get_settings
from tinysaas.infrastructure.logging import StructlogLogger, configure_logging
from tinysaas.infrastructure.resources import Resources

ROUTER_MODULES = [
    "tinysaas.adapters.web.routers.auth",
    "tinysaas.adapters.web.routers.users",
    "tinysaas.adapters.web.routers.billing",
    "tinysaas.adapters.web.routers.services",
    "tinysaas.adapters.web.routers.admin",
    "tinysaas.adapters.web.routers.files",
    "tinysaas.adapters.web.routers.webhooks",
    "tinysaas.adapters.web.routers.health",
]


def build_app_options(settings: Settings) -> AppOptions:
    return settings.build_app_options()


class Container(containers.DeclarativeContainer):
    """Application container (see the module docstring)."""

    wiring_config = containers.WiringConfiguration(modules=ROUTER_MODULES, auto_wire=True)

    # ---- configuration ------------------------------------------------
    settings = providers.Singleton(get_settings)
    options = providers.Singleton(build_app_options, settings=settings)

    # ---- process resources --------------------------------------------
    # Built synchronously (drivers only) and started/shut down by the lifespan.
    resources = providers.Singleton(Resources, settings=settings)

    # ---- generic collaborators ---------------------------------------
    logger = providers.Singleton(StructlogLogger)
    telemetry = providers.Singleton(
        lambda dsn: SentryTelemetry(enabled=bool(dsn)), dsn=settings.provided.sentry_dsn
    )
    clock = providers.Singleton(SystemClock)
    ids = providers.Singleton(UuidGenerator)
    cookie_policy = providers.Singleton(build_cookie_policy, settings=settings)

    # ---- security -----------------------------------------------------
    password_hasher = providers.Singleton(
        Argon2PasswordHasher,
        time_cost=settings.provided.argon2_time_cost,
        memory_cost=settings.provided.argon2_memory_cost,
        parallelism=settings.provided.argon2_parallelism,
    )
    token_service = providers.Singleton(
        PyJWTTokenService,
        secret_key=settings.provided.jwt_secret_key,
        algorithm=settings.provided.jwt_algorithm,
        issuer=settings.provided.jwt_issuer,
        audience=settings.provided.jwt_audience,
        access_token_ttl_seconds=settings.provided.access_token_ttl_seconds,
    )
    api_key_service = providers.Singleton(
        HashedApiKeyService,
        prefix=settings.provided.api_key_prefix,
        salt=settings.provided.jwt_secret_key,
    )

    # ---- outbound adapters -------------------------------------------
    rate_limiter = providers.Singleton(RedisRateLimiter, client=resources.provided.redis)
    renderer = providers.Singleton(TemplateRenderer)
    mailer = providers.Selector(
        settings.provided.mailer,
        console=providers.Singleton(
            ConsoleMailer,
            renderer=renderer,
            outbox_dir=settings.provided.mail_outbox_dir,
            from_address=settings.provided.mail_from,
            logger=logger,
        ),
        resend=providers.Singleton(
            ResendMailer,
            renderer=renderer,
            http_client=resources.provided.http_client,
            api_key=settings.provided.resend_api_key,
            from_address=settings.provided.mail_from,
            base_url=settings.provided.resend_base_url,
        ),
    )
    storage = providers.Selector(
        settings.provided.storage_backend,
        s3=providers.Singleton(S3ObjectStorage, storage=resources.provided.s3),
        memory=providers.Singleton(InMemoryObjectStorage),
    )
    in_process_executor = providers.Singleton(
        InProcessServiceExecutor, handlers=providers.Callable(build_demo_handlers)
    )
    proxy_executor = providers.Singleton(
        HttpProxyServiceExecutor, http_client=resources.provided.http_client
    )
    executor = providers.Singleton(
        CompositeServiceExecutor,
        proxy=proxy_executor,
        in_process=in_process_executor,
        in_process_enabled=settings.provided.demo_executor_enabled,
    )
    task_queue = providers.Singleton(ArqTaskQueue, resources=resources)
    payment_gateway = providers.Singleton(
        StripePaymentGateway,
        secret_key=settings.provided.stripe_secret_key,
        webhook_secret=settings.provided.stripe_webhook_secret,
    )

    # ---- persistence --------------------------------------------------
    session_factory = providers.Callable(
        lambda resources: resources.postgres.session_maker, resources=resources
    )
    uow_factory = providers.Singleton(SqlAlchemyUnitOfWorkFactory, session_factory=session_factory)

    # ---- domain services ---------------------------------------------
    credit_reservations = providers.Singleton(CreditReservationService)

    # ---- application collaborators -----------------------------------
    session_issuer = providers.Singleton(
        SessionIssuer, token_service=token_service, clock=clock, options=options
    )
    one_time_tokens = providers.Singleton(
        OneTimeTokenIssuer, token_service=token_service, clock=clock, options=options
    )
    settlement = providers.Singleton(
        InvocationSettlement,
        uow_factory=uow_factory,
        credits=credit_reservations,
        clock=clock,
        logger=logger,
    )

    # ---- use cases: identity -----------------------------------------
    register_user_use_case = providers.Factory(
        RegisterUserUseCase,
        uow_factory=uow_factory,
        password_hasher=password_hasher,
        session_issuer=session_issuer,
        one_time_tokens=one_time_tokens,
        mailer=mailer,
        options=options,
        clock=clock,
        logger=logger,
    )
    login_use_case = providers.Factory(
        LoginUseCase,
        uow_factory=uow_factory,
        password_hasher=password_hasher,
        session_issuer=session_issuer,
        options=options,
        clock=clock,
        logger=logger,
    )
    refresh_session_use_case = providers.Factory(
        RefreshSessionUseCase,
        uow_factory=uow_factory,
        token_service=token_service,
        session_issuer=session_issuer,
        clock=clock,
        logger=logger,
    )
    logout_use_case = providers.Factory(
        LogoutUseCase, uow_factory=uow_factory, token_service=token_service, clock=clock
    )
    logout_all_use_case = providers.Factory(LogoutAllUseCase, uow_factory=uow_factory, clock=clock)
    list_sessions_use_case = providers.Factory(
        ListSessionsUseCase, uow_factory=uow_factory, clock=clock
    )
    revoke_session_use_case = providers.Factory(
        RevokeSessionUseCase, uow_factory=uow_factory, clock=clock
    )
    authenticate_request_use_case = providers.Factory(
        AuthenticateRequestUseCase,
        uow_factory=uow_factory,
        token_service=token_service,
        api_key_service=api_key_service,
        clock=clock,
        logger=logger,
    )
    verify_email_use_case = providers.Factory(
        VerifyEmailUseCase, uow_factory=uow_factory, token_service=token_service, clock=clock
    )
    request_password_reset_use_case = providers.Factory(
        RequestPasswordResetUseCase,
        uow_factory=uow_factory,
        one_time_tokens=one_time_tokens,
        mailer=mailer,
        options=options,
        clock=clock,
        logger=logger,
    )
    reset_password_use_case = providers.Factory(
        ResetPasswordUseCase,
        uow_factory=uow_factory,
        password_hasher=password_hasher,
        token_service=token_service,
        clock=clock,
    )
    get_profile_use_case = providers.Factory(GetProfileUseCase, uow_factory=uow_factory)
    update_profile_use_case = providers.Factory(
        UpdateProfileUseCase, uow_factory=uow_factory, clock=clock
    )
    change_password_use_case = providers.Factory(
        ChangePasswordUseCase,
        uow_factory=uow_factory,
        password_hasher=password_hasher,
        clock=clock,
    )
    create_api_key_use_case = providers.Factory(
        CreateApiKeyUseCase,
        uow_factory=uow_factory,
        api_key_service=api_key_service,
        options=options,
        clock=clock,
    )
    list_api_keys_use_case = providers.Factory(ListApiKeysUseCase, uow_factory=uow_factory)
    revoke_api_key_use_case = providers.Factory(
        RevokeApiKeyUseCase, uow_factory=uow_factory, clock=clock
    )

    # ---- use cases: billing ------------------------------------------
    list_packages_use_case = providers.Factory(ListCreditPackagesUseCase, uow_factory=uow_factory)
    get_wallet_use_case = providers.Factory(GetWalletUseCase, uow_factory=uow_factory, clock=clock)
    list_ledger_use_case = providers.Factory(ListLedgerUseCase, uow_factory=uow_factory)
    start_topup_use_case = providers.Factory(
        StartTopUpUseCase,
        uow_factory=uow_factory,
        gateway=payment_gateway,
        options=options,
        clock=clock,
        logger=logger,
    )
    handle_topup_webhook_use_case = providers.Factory(
        HandleTopUpWebhookUseCase,
        uow_factory=uow_factory,
        gateway=payment_gateway,
        mailer=mailer,
        options=options,
        clock=clock,
        logger=logger,
    )
    get_topup_use_case = providers.Factory(GetTopUpUseCase, uow_factory=uow_factory)
    grant_credits_use_case = providers.Factory(
        GrantCreditsUseCase, uow_factory=uow_factory, clock=clock, logger=logger
    )

    # ---- use cases: catalog / dispatch -------------------------------
    create_service_use_case = providers.Factory(
        CreateServiceUseCase, uow_factory=uow_factory, clock=clock
    )
    update_service_use_case = providers.Factory(
        UpdateServiceUseCase, uow_factory=uow_factory, clock=clock
    )
    deactivate_service_use_case = providers.Factory(
        DeactivateServiceUseCase, uow_factory=uow_factory, clock=clock
    )
    list_services_use_case = providers.Factory(ListServicesUseCase, uow_factory=uow_factory)
    get_service_use_case = providers.Factory(GetServiceUseCase, uow_factory=uow_factory)
    execute_service_use_case = providers.Factory(
        ExecuteServiceUseCase,
        uow_factory=uow_factory,
        credits=credit_reservations,
        executor=executor,
        settlement=settlement,
        clock=clock,
        logger=logger,
    )
    submit_service_task_use_case = providers.Factory(
        SubmitServiceTaskUseCase,
        uow_factory=uow_factory,
        credits=credit_reservations,
        queue=task_queue,
        clock=clock,
        logger=logger,
    )
    run_service_task_use_case = providers.Factory(
        RunServiceTaskUseCase,
        uow_factory=uow_factory,
        credits=credit_reservations,
        executor=executor,
        settlement=settlement,
        clock=clock,
        logger=logger,
    )
    get_task_use_case = providers.Factory(GetTaskUseCase, uow_factory=uow_factory)
    list_my_invocations_use_case = providers.Factory(
        ListMyInvocationsUseCase, uow_factory=uow_factory
    )
    get_invocation_use_case = providers.Factory(GetInvocationUseCase, uow_factory=uow_factory)
    list_all_invocations_use_case = providers.Factory(
        ListAllInvocationsUseCase, uow_factory=uow_factory
    )

    # ---- use cases: admin / files / health ---------------------------
    list_users_use_case = providers.Factory(ListUsersUseCase, uow_factory=uow_factory, clock=clock)
    get_user_use_case = providers.Factory(GetUserUseCase, uow_factory=uow_factory)
    update_user_use_case = providers.Factory(
        UpdateUserUseCase, uow_factory=uow_factory, clock=clock
    )
    presign_upload_use_case = providers.Factory(
        PresignUploadUseCase, storage=storage, options=options
    )
    presign_download_use_case = providers.Factory(
        PresignDownloadUseCase, storage=storage, options=options
    )
    check_readiness_use_case = providers.Factory(
        CheckReadinessUseCase,
        probes=providers.Callable(
            lambda resources: resources.readiness_probes(), resources=resources
        ),
    )


async def start_resources(container: Container) -> None:
    """Open connections (FastAPI lifespan / worker startup)."""
    await container.resources().start()


async def stop_resources(container: Container) -> None:
    """Close connections (FastAPI lifespan / worker shutdown)."""
    await container.resources().shutdown()


def build_container(settings: Settings | None = None) -> Container:
    """Create the container, configure logging/Sentry and wire the modules."""
    resolved = settings or get_settings()
    configure_logging(resolved)
    init_sentry(resolved)
    container = Container()
    if settings is not None:
        container.settings.override(providers.Singleton(lambda: settings))
    container.wire(modules=ROUTER_MODULES)
    return container


__all__ = [
    "Container",
    "Resources",
    "ROUTER_MODULES",
    "build_container",
    "start_resources",
    "stop_resources",
]
