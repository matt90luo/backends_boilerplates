"""Shared fixtures: an app wired with in-memory adapters and no external services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from dependency_injector import providers

from tests.fakes.clock import FakeClock
from tests.fakes.external import FakeMailer, FakePaymentGateway, FakeRateLimiter, StubExecutor
from tests.fakes.memory import InMemoryUnitOfWorkFactory, MemoryStore
from tests.fakes.security import FakeApiKeyService, FakePasswordHasher, FakeTokenService
from tinysaas.adapters.queue.memory import InMemoryTaskQueue
from tinysaas.adapters.storage.memory import InMemoryObjectStorage
from tinysaas.adapters.web.app import create_app
from tinysaas.application.use_cases.readiness import CheckReadinessUseCase
from tinysaas.containers.container import Container, build_container
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.catalog.service import ExecMode, Service
from tinysaas.domain.identity.user import Plan, Role, User
from tinysaas.infrastructure.config import Settings

TEST_PASSWORD = "Passw0rd!23"
ADMIN_PASSWORD = "Adminpass1"


@dataclass
class AppContext:
    """Everything a test may want to poke at."""

    settings: Settings
    container: Container
    store: MemoryStore
    clock: FakeClock
    mailer: FakeMailer
    limiter: FakeRateLimiter
    executor: StubExecutor
    gateway: FakePaymentGateway
    queue: InMemoryTaskQueue
    storage: InMemoryObjectStorage
    hasher: FakePasswordHasher = field(default_factory=FakePasswordHasher)

    def seed_package(
        self,
        *,
        slug: str = "starter",
        price_id: str = "price_starter",
        credits: int = 100,
        amount_minor: int = 500,
    ) -> CreditPackage:
        package = CreditPackage(
            id=uuid4(),
            slug=slug,
            name=slug.title(),
            credits=credits,
            amount_minor=amount_minor,
            currency="usd",
            stripe_price_id=price_id,
        )
        return self.store.add_package(package)

    def seed_service(
        self,
        *,
        slug: str = "echo",
        credit_cost: int = 1,
        exec_mode: ExecMode = ExecMode.SYNC,
        upstream_url: str | None = None,
        is_active: bool = True,
    ) -> Service:
        service = Service.create(
            slug=slug,
            name=slug.title(),
            credit_cost=credit_cost,
            exec_mode=exec_mode,
            upstream_url=upstream_url,
            is_active=is_active,
        )
        return self.store.add_service(service)

    def seed_user(
        self,
        *,
        email: str,
        password: str,
        role: Role = Role.USER,
        plan: Plan = Plan.FREE,
        daily_quota: int = 20,
        balance: int = 0,
        is_active: bool = True,
    ) -> User:
        user = User.register(
            email=email,
            password_hash=self.hasher.hash(password),
            role=role,
            plan=plan,
            daily_quota=daily_quota,
        )
        user.is_active = is_active
        self.store.users[user.id] = user
        self.store.wallets[user.id] = Wallet.for_user(user.id, now=self.clock.now())
        if balance:
            from tinysaas.domain.billing.credits import CreditAmount

            wallet = self.store.wallets[user.id]
            wallet.top_up(CreditAmount(balance), reference="seed", now=self.clock.now())
        return user

    def wallet_of(self, user_id) -> Wallet:  # type: ignore[no-untyped-def]
        return self.store.wallets[user_id]

    def balance_of(self, user_id) -> int:  # type: ignore[no-untyped-def]
        return self.store.wallets[user_id].balance

    def ledger_kinds(self, user_id) -> list[str]:  # type: ignore[no-untyped-def]
        entries = [e for e in self.store.ledger.values() if e.user_id == user_id]
        entries.sort(key=lambda e: e.created_at)
        return [entry.kind.value for entry in entries]


def build_test_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "log_level": "WARNING",
        "log_json": False,
        "mailer": "console",
        "storage_backend": "memory",
        "rate_limit_enabled": True,
        "rate_limit_login_per_minute": 5,
        "rate_limit_register_per_hour": 10,
        "rate_limit_service_per_minute": 60,
        "require_email_verification": False,
        "public_base_url": "http://dashboard.test",
        "sentry_dsn": None,
        "jwt_secret_key": "unit-test-secret-that-is-long-enough",
        "demo_executor_enabled": True,
        "admin_email": "admin@tinysaas.test",
        "admin_password": ADMIN_PASSWORD,
    }
    values.update(overrides)
    return Settings(**values, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture(autouse=True, scope="session")
def _inline_default_threadpool() -> Iterator[None]:
    """Run "threadpool" work inline during tests.

    FastAPI executes *synchronous* dependencies (which is how
    ``Depends(Provide[...])`` providers are resolved) through
    ``anyio.to_thread.run_sync``. Some CI containers cannot start anyio worker
    threads, which would make every request hang, while all the work we push
    there is pure CPU/DI resolution. Executing it on the event loop keeps the
    suite hermetic and fast.
    """
    import anyio.to_thread

    original = anyio.to_thread.run_sync

    async def run_inline(func: object, *args: object, **kwargs: object) -> object:
        kwargs.pop("abandon_on_cancel", None)
        kwargs.pop("cancellable", None)
        kwargs.pop("limiter", None)
        return func(*args, **kwargs)  # type: ignore[operator]

    anyio.to_thread.run_sync = run_inline  # type: ignore[assignment]
    try:
        yield
    finally:
        anyio.to_thread.run_sync = original


@pytest.fixture
def ctx() -> AppContext:
    settings = build_test_settings()
    container = build_container(settings)
    store = MemoryStore()
    clock = FakeClock()
    mailer = FakeMailer()
    limiter = FakeRateLimiter()
    executor = StubExecutor()
    gateway = FakePaymentGateway()
    queue = InMemoryTaskQueue()
    storage = InMemoryObjectStorage()
    hasher = FakePasswordHasher()

    container.uow_factory.override(providers.Object(InMemoryUnitOfWorkFactory(store)))
    container.rate_limiter.override(providers.Object(limiter))
    container.mailer.override(providers.Object(mailer))
    container.storage.override(providers.Object(storage))
    container.executor.override(providers.Object(executor))
    container.task_queue.override(providers.Object(queue))
    container.payment_gateway.override(providers.Object(gateway))
    container.password_hasher.override(providers.Object(hasher))
    container.clock.override(providers.Object(clock))
    container.token_service.override(providers.Object(FakeTokenService(clock=lambda: clock.now())))
    container.api_key_service.override(providers.Object(FakeApiKeyService()))
    container.check_readiness_use_case.override(providers.Object(CheckReadinessUseCase(probes=[])))

    return AppContext(
        settings=settings,
        container=container,
        store=store,
        clock=clock,
        mailer=mailer,
        limiter=limiter,
        executor=executor,
        gateway=gateway,
        queue=queue,
        storage=storage,
        hasher=hasher,
    )


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(ctx.container))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client: httpx.AsyncClient, *, email: str, password: str = TEST_PASSWORD) -> dict:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def login(client: httpx.AsyncClient, *, email: str, password: str = TEST_PASSWORD) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def login_admin(client: httpx.AsyncClient, ctx: AppContext) -> dict:
    email = str(ctx.settings.admin_email)
    ctx.seed_user(
        email=email,
        password=ADMIN_PASSWORD,
        role=Role.ADMIN,
        plan=Plan.PRO,
        daily_quota=1000,
        balance=10_000,
    )
    return await login(client, email=email, password=ADMIN_PASSWORD)


def expires_at(*, days: int = 1) -> datetime:
    from datetime import timedelta

    return datetime.now(UTC) + timedelta(days=days)
