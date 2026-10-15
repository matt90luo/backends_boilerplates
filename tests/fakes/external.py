"""Fakes for mailer, rate limiter, executor, queue and the payment gateway."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from tinysaas.application.errors import InvalidWebhookSignature, PaymentConfigurationError
from tinysaas.application.ports.external import (
    CheckoutSession,
    EmailMessage,
    ExecutionResult,
    PackagePrice,
    RateLimitDecision,
    TopUpEvent,
)
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import PaymentOutcome
from tinysaas.domain.catalog.service import Service

WEBHOOK_SIGNATURE = "test-signature"


class FakeMailer:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self.failures: set[str] = set()

    async def send(self, message: EmailMessage) -> None:
        if message.template in self.failures:
            raise RuntimeError("smtp down")
        self.messages.append(message)

    def templates(self) -> list[str]:
        return [message.template for message in self.messages]


class FakeRateLimiter:
    """Counts hits per key; ``limit_override`` forces a decision."""

    def __init__(self, *, limit_override: int | None = None) -> None:
        self._limit_override = limit_override
        self.hits: dict[str, int] = {}

    async def hit(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        self.hits[key] = self.hits.get(key, 0) + 1
        effective = self._limit_override if self._limit_override is not None else limit
        if effective <= 0 or self.hits[key] > effective:
            return RateLimitDecision(
                allowed=False, limit=effective, remaining=0, retry_after_seconds=window_seconds
            )
        return RateLimitDecision(
            allowed=True,
            limit=effective,
            remaining=effective - self.hits[key],
            retry_after_seconds=0,
        )


@dataclass
class StubExecutor:
    """Returns a canned result; ``ok=False`` simulates an upstream failure."""

    ok: bool = True
    status_code: int | None = 200
    body: bytes = b'{"ok":true}'
    content_type: str = "application/json"
    error_code: str | None = None
    error_message: str | None = None
    calls: list[str] = field(default_factory=list)

    async def execute(
        self,
        *,
        service: Service,
        payload: bytes,
        content_type: str,
        headers: Mapping[str, str],
    ) -> ExecutionResult:
        self.calls.append(service.slug)
        return ExecutionResult(
            ok=self.ok,
            status_code=self.status_code,
            body=self.body if self.ok else b'{"error":"upstream down"}',
            content_type=self.content_type,
            latency_ms=7,
            error_code=self.error_code,
            error_message=self.error_message,
        )


class FakePaymentGateway:
    """Price lookup and Checkout creation without touching Stripe."""

    def __init__(self, *, prices: dict[str, int] | None = None) -> None:
        self._prices = prices or {}
        self.sessions: list[tuple[UUID, str]] = []
        self.webhook_events: dict[tuple[bytes, str], TopUpEvent | None] = {}

    async def get_price(self, price_id: str) -> PackagePrice:
        if price_id not in self._prices and not price_id.startswith("price_"):
            raise PaymentConfigurationError(f"unknown price {price_id}")
        return PackagePrice(
            price_id=price_id,
            product_id="prod_test",
            amount_minor=self._prices.get(price_id, 500),
            currency="usd",
        )

    async def create_checkout_session(
        self,
        *,
        package: CreditPackage,
        user_id: UUID,
        topup_id: UUID,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> CheckoutSession:
        self.sessions.append((topup_id, idempotency_key))
        return CheckoutSession(
            session_id=f"cs_test_{topup_id}", url=f"https://checkout.stripe.test/{topup_id}"
        )

    def parse_webhook(self, payload: bytes, signature: str) -> TopUpEvent | None:
        if signature != WEBHOOK_SIGNATURE:
            raise InvalidWebhookSignature("Stripe webhook 签名无效")
        data = json.loads(payload)
        if data.get("type") not in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
            "checkout.session.expired",
        }:
            return None
        outcome = None
        if data.get("type") == "checkout.session.completed":
            outcome = PaymentOutcome.PAID
        elif data.get("type") == "checkout.session.async_payment_failed":
            outcome = PaymentOutcome.FAILED
        elif data.get("type") == "checkout.session.expired":
            outcome = PaymentOutcome.CANCELED
        return TopUpEvent(
            event_id=str(data["id"]),
            event_type=str(data["type"]),
            topup_id=UUID(str(data["topup_id"])),
            checkout_session_id=str(data["session_id"]),
            outcome=outcome,
        )


def webhook_payload(
    *,
    event_id: str,
    topup_id: UUID,
    session_id: str,
    event_type: str = "checkout.session.completed",
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "topup_id": str(topup_id),
            "session_id": session_id,
        }
    ).encode("utf-8")


def monotonic_clock() -> float:  # pragma: no cover - helper for tests
    return time.monotonic()
