"""Ports for everything outside the process boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import PaymentOutcome
from tinysaas.domain.catalog.service import Service


# --- notifications ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EmailMessage:
    """A templated transactional email request."""

    to: str
    subject: str
    template: str
    context: Mapping[str, object] = field(default_factory=dict)


class Mailer(Protocol):
    """Renders a template and delivers it (console, Resend, ...)."""

    async def send(self, message: EmailMessage) -> None: ...


# --- object storage --------------------------------------------------------
class ObjectStorage(Protocol):
    async def presign_put(self, *, key: str, content_type: str, expires_in: int) -> str: ...

    async def presign_get(
        self, *, key: str, expires_in: int, download_name: str | None = None
    ) -> str: ...

    async def exists(self, *, key: str) -> bool: ...


# --- payments --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PackagePrice:
    """The authoritative amount coming from the payment provider."""

    price_id: str
    product_id: str
    amount_minor: int
    currency: str
    livemode: bool = False


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    session_id: str
    url: str


@dataclass(frozen=True, slots=True)
class TopUpEvent:
    """A provider agnostic view of a checkout webhook."""

    event_id: str
    event_type: str
    topup_id: UUID
    checkout_session_id: str
    outcome: PaymentOutcome | None


class PaymentGateway(Protocol):
    async def get_price(self, price_id: str) -> PackagePrice: ...

    async def create_checkout_session(
        self,
        *,
        package: CreditPackage,
        user_id: UUID,
        topup_id: UUID,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> CheckoutSession: ...

    def parse_webhook(self, payload: bytes, signature: str) -> TopUpEvent | None: ...


# --- rate limiting ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    async def hit(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision: ...


# --- queue -----------------------------------------------------------------
class TaskQueue(Protocol):
    async def enqueue(
        self, task_name: str, payload: dict[str, object], *, job_id: str | None = None
    ) -> str | None:
        """Enqueue a background job; returns the job id when the backend has one."""
        ...


# --- service execution -----------------------------------------------------
@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of one upstream call (success or failure, never an exception)."""

    ok: bool
    status_code: int | None
    body: bytes
    content_type: str
    latency_ms: int
    error_code: str | None = None
    error_message: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


class ServiceExecutor(Protocol):
    """Dispatches a payload to the implementation behind a service."""

    async def execute(
        self,
        *,
        service: Service,
        payload: bytes,
        content_type: str,
        headers: Mapping[str, str],
    ) -> ExecutionResult: ...


# --- readiness -------------------------------------------------------------
class ReadinessProbe(Protocol):
    """A named dependency that must answer quickly for ``/readyz``."""

    name: str

    async def ping(self) -> None:
        """Raise when the dependency is unhealthy."""
        ...
