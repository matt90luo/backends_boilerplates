"""Stripe Checkout adapter for credit top-ups (see babypay for the reference)."""

from __future__ import annotations

from uuid import UUID

import stripe

from tinysaas.application.errors import (
    InvalidPaymentEvent,
    InvalidWebhookSignature,
    PaymentConfigurationError,
    PaymentProviderError,
)
from tinysaas.application.ports.external import CheckoutSession, PackagePrice, TopUpEvent
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import PaymentOutcome

_SUPPORTED_EVENTS = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
}


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class StripePaymentGateway:
    """Adapter implementing :class:`PaymentGateway`.

    The checkout amount always comes from the Stripe Price, never from the
    client, so a tampered request cannot buy credits at a discount.
    """

    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str,
        client: object | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._client = client or (stripe.StripeClient(secret_key) if secret_key else None)

    def _require_configuration(self) -> None:
        if self._client is None:
            raise PaymentConfigurationError("STRIPE_SECRET_KEY 未配置")
        if not self._webhook_secret:
            raise PaymentConfigurationError("STRIPE_WEBHOOK_SECRET 未配置")

    async def get_price(self, price_id: str) -> PackagePrice:
        if self._client is None:
            raise PaymentConfigurationError("STRIPE_SECRET_KEY 未配置")
        if not price_id:
            raise PaymentConfigurationError("套餐缺少 Stripe Price ID")
        client = self._client
        try:
            price = await client.v1.prices.retrieve_async(price_id)  # type: ignore[attr-defined]
        except Exception as error:
            raise PaymentConfigurationError(f"无法读取 Stripe Price {price_id}") from error

        amount = _field(price, "unit_amount")
        if not isinstance(amount, int) or amount <= 0:
            raise PaymentConfigurationError("Stripe Price 必须是固定金额")
        if not _field(price, "active") or _field(price, "recurring") is not None:
            raise PaymentConfigurationError("Stripe Price 必须处于激活状态且为一次性价格")
        product = _field(price, "product")
        product_id = product if isinstance(product, str) else str(_field(product, "id", ""))
        return PackagePrice(
            price_id=price_id,
            product_id=product_id,
            amount_minor=amount,
            currency=str(_field(price, "currency", "usd")).lower(),
            livemode=bool(_field(price, "livemode", False)),
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
        if self._client is None:
            raise PaymentConfigurationError("STRIPE_SECRET_KEY 未配置")
        client = self._client
        try:
            session = await client.v1.checkout.sessions.create_async(  # type: ignore[attr-defined]
                {
                    "mode": "payment",
                    "line_items": [{"price": package.stripe_price_id, "quantity": 1}],
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "client_reference_id": str(topup_id),
                    "metadata": {
                        "topup_id": str(topup_id),
                        "user_id": str(user_id),
                        "package_slug": package.slug,
                        "credits": str(package.credits),
                    },
                },
                {"idempotency_key": idempotency_key},
            )
        except Exception as error:
            raise PaymentProviderError("无法创建 Stripe Checkout Session") from error
        url = _field(session, "url")
        if not url:
            raise PaymentConfigurationError("Stripe 未返回 Checkout URL")
        return CheckoutSession(session_id=str(_field(session, "id")), url=str(url))

    def parse_webhook(self, payload: bytes, signature: str) -> TopUpEvent | None:
        if not self._webhook_secret:
            raise PaymentConfigurationError("STRIPE_WEBHOOK_SECRET 未配置")
        try:
            event = stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as error:
            raise InvalidWebhookSignature("Stripe webhook 签名无效") from error

        event_id = _field(event, "id")
        event_type = _field(event, "type")
        if event_type not in _SUPPORTED_EVENTS:
            return None

        data = _field(event, "data", {})
        session = _field(data, "object", {})
        metadata = _field(session, "metadata") or {}
        topup_id = _field(metadata, "topup_id")
        session_id = _field(session, "id")
        try:
            parsed_topup_id = UUID(str(topup_id))
        except (TypeError, ValueError):
            return None
        if not isinstance(session_id, str) or not session_id:
            raise InvalidPaymentEvent("Stripe Checkout 事件缺少 session id")

        outcome: PaymentOutcome | None = None
        if event_type == "checkout.session.completed":
            if _field(session, "payment_status") == "paid":
                outcome = PaymentOutcome.PAID
        elif event_type == "checkout.session.async_payment_succeeded":
            outcome = PaymentOutcome.PAID
        elif event_type == "checkout.session.async_payment_failed":
            outcome = PaymentOutcome.FAILED
        elif event_type == "checkout.session.expired":
            outcome = PaymentOutcome.CANCELED

        return TopUpEvent(
            event_id=str(event_id),
            event_type=str(event_type),
            topup_id=parsed_topup_id,
            checkout_session_id=session_id,
            outcome=outcome,
        )
