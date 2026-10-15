"""The Stripe adapter: price validation, checkout creation and webhook parsing."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tinysaas.adapters.payments.stripe_gateway import StripePaymentGateway
from tinysaas.application.errors import (
    InvalidPaymentEvent,
    InvalidWebhookSignature,
    PaymentConfigurationError,
    PaymentProviderError,
)
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import PaymentOutcome

WEBHOOK_SECRET = "whsec_unit_test"


class FakeStripeClient:
    """Mimics the parts of ``stripe.StripeClient`` we rely on."""

    def __init__(
        self,
        *,
        price: dict | None = None,
        session: dict | None = None,
        price_error: Exception | None = None,
        session_error: Exception | None = None,
    ) -> None:
        self._price = price or _active_price()
        self._session = session or {"id": "cs_test_1", "url": "https://checkout.stripe.test/1"}
        self._price_error = price_error
        self._session_error = session_error
        self.checkout_params: dict | None = None
        self.checkout_options: dict | None = None

        async def retrieve_async(price_id: str) -> dict:
            if self._price_error:
                raise self._price_error
            return self._price

        async def create_async(params: dict, options: dict | None = None) -> dict:
            if self._session_error:
                raise self._session_error
            self.checkout_params = params
            self.checkout_options = options or {}
            return self._session

        self.v1 = SimpleNamespace(
            prices=SimpleNamespace(retrieve_async=retrieve_async),
            checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create_async)),
        )


def _active_price(**overrides: object) -> dict:
    price: dict[str, object] = {
        "id": "price_starter",
        "object": "price",
        "active": True,
        "recurring": None,
        "unit_amount": 500,
        "currency": "usd",
        "livemode": False,
        "product": "prod_test",
    }
    price.update(overrides)
    return price


def make_package() -> CreditPackage:
    return CreditPackage(
        id=uuid4(),
        slug="starter",
        name="Starter",
        credits=100,
        amount_minor=500,
        currency="usd",
        stripe_price_id="price_starter",
    )


def sign(payload: bytes, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    moment = timestamp or int(time.time())
    signature = hmac.new(
        secret.encode(), f"{moment}.{payload.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={moment},v1={signature}"


@pytest.mark.asyncio
async def test_get_price_returns_the_authoritative_amount() -> None:
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient()
    )

    price = await gateway.get_price("price_starter")

    assert price.price_id == "price_starter"
    assert price.amount_minor == 500
    assert price.currency == "usd"
    assert price.livemode is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "price",
    [
        _active_price(active=False),
        _active_price(recurring={"interval": "month"}),
        _active_price(unit_amount=None),
        _active_price(unit_amount=0),
    ],
)
async def test_get_price_rejects_unusable_prices(price: dict) -> None:
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient(price=price)
    )

    with pytest.raises(PaymentConfigurationError):
        await gateway.get_price("price_starter")


@pytest.mark.asyncio
async def test_get_price_requires_a_secret_key() -> None:
    gateway = StripePaymentGateway(secret_key="", webhook_secret=WEBHOOK_SECRET)

    with pytest.raises(PaymentConfigurationError):
        await gateway.get_price("price_starter")


@pytest.mark.asyncio
async def test_create_checkout_session_forwards_metadata_and_idempotency() -> None:
    client = FakeStripeClient()
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=client
    )
    package = make_package()
    user_id, topup_id = uuid4(), uuid4()

    session = await gateway.create_checkout_session(
        package=package,
        user_id=user_id,
        topup_id=topup_id,
        success_url="http://dash/success",
        cancel_url="http://dash/cancel",
        idempotency_key=str(topup_id),
    )

    assert session.session_id == "cs_test_1"
    assert session.url.startswith("https://checkout.stripe.test")
    assert client.checkout_params is not None
    assert client.checkout_params["mode"] == "payment"
    assert client.checkout_params["line_items"] == [{"price": "price_starter", "quantity": 1}]
    assert client.checkout_params["metadata"]["credits"] == "100"
    assert client.checkout_params["metadata"]["topup_id"] == str(topup_id)
    assert client.checkout_options == {"idempotency_key": str(topup_id)}


@pytest.mark.asyncio
async def test_create_checkout_wraps_provider_errors() -> None:
    client = FakeStripeClient(session_error=RuntimeError("stripe exploded"))
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=client
    )

    with pytest.raises(PaymentProviderError):
        await gateway.create_checkout_session(
            package=make_package(),
            user_id=uuid4(),
            topup_id=uuid4(),
            success_url="http://dash/success",
            cancel_url="http://dash/cancel",
            idempotency_key="key",
        )


def test_parse_webhook_accepts_a_valid_signature() -> None:
    topup_id = uuid4()
    payload = json.dumps(
        {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_1",
                    "payment_status": "paid",
                    "metadata": {"topup_id": str(topup_id)},
                }
            },
        }
    ).encode()
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient()
    )

    event = gateway.parse_webhook(payload, sign(payload))

    assert event is not None
    assert event.event_id == "evt_1"
    assert event.topup_id == topup_id
    assert event.checkout_session_id == "cs_test_1"
    assert event.outcome is PaymentOutcome.PAID


def test_parse_webhook_rejects_a_forged_signature() -> None:
    payload = b'{"id": "evt_1", "type": "checkout.session.completed"}'
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient()
    )

    with pytest.raises(InvalidWebhookSignature):
        gateway.parse_webhook(payload, sign(payload, secret="wrong-secret"))


def test_parse_webhook_ignores_unknown_events_and_missing_metadata() -> None:
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient()
    )

    unrelated = json.dumps({"id": "evt_2", "type": "payment_intent.created"}).encode()
    assert gateway.parse_webhook(unrelated, sign(unrelated)) is None

    without_metadata = json.dumps(
        {
            "id": "evt_3",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_status": "paid", "metadata": {}}},
        }
    ).encode()
    assert gateway.parse_webhook(without_metadata, sign(without_metadata)) is None


def test_parse_webhook_maps_unpaid_and_expired_sessions() -> None:
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient()
    )
    topup_id = uuid4()

    def payload_for(event_type: str, payment_status: str) -> bytes:
        return json.dumps(
            {
                "id": f"evt_{event_type}",
                "type": event_type,
                "data": {
                    "object": {
                        "id": "cs_1",
                        "payment_status": payment_status,
                        "metadata": {"topup_id": str(topup_id)},
                    }
                },
            }
        ).encode()

    unfinished = payload_for("checkout.session.completed", "unpaid")
    event = gateway.parse_webhook(unfinished, sign(unfinished))
    assert event is not None and event.outcome is None

    expired = payload_for("checkout.session.expired", "unpaid")
    event = gateway.parse_webhook(expired, sign(expired))
    assert event is not None and event.outcome is PaymentOutcome.CANCELED

    failed = payload_for("checkout.session.async_payment_failed", "unpaid")
    event = gateway.parse_webhook(failed, sign(failed))
    assert event is not None and event.outcome is PaymentOutcome.FAILED


def test_parse_webhook_requires_a_session_id() -> None:
    payload = json.dumps(
        {
            "id": "evt_4",
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"topup_id": str(uuid4())}}},
        }
    ).encode()
    gateway = StripePaymentGateway(
        secret_key="sk_test", webhook_secret=WEBHOOK_SECRET, client=FakeStripeClient()
    )

    with pytest.raises(InvalidPaymentEvent):
        gateway.parse_webhook(payload, sign(payload))
