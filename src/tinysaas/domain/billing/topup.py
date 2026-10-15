"""Credit top-up aggregate (Stripe Checkout driven)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from tinysaas.domain.errors import ValidationError


class TopUpStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"


class PaymentOutcome(StrEnum):
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class TopUp:
    """A pending or settled credit purchase.

    ``idempotency_key`` makes ``POST /billing/checkout`` safe to retry: the same
    key returns the very same Checkout Session instead of charging twice.
    """

    id: UUID
    user_id: UUID
    package_id: UUID | None
    package_slug: str
    credits: int
    amount_minor: int
    currency: str
    idempotency_key: str
    status: TopUpStatus = TopUpStatus.PENDING
    checkout_session_id: str | None = None
    checkout_url: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        package_id: UUID,
        package_slug: str,
        credits: int,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> TopUp:
        if not 1 <= len(idempotency_key) <= 255:
            raise ValidationError(
                "Idempotency-Key 长度必须在 1-255 之间", details={"field": "Idempotency-Key"}
            )
        if credits <= 0:
            raise ValidationError("充值 credit 数量必须大于 0", details={"field": "credits"})
        if amount_minor <= 0:
            raise ValidationError("充值金额必须大于 0", details={"field": "amount"})
        normalized_currency = currency.strip().lower()
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ValidationError("货币必须是三位 ISO 代码", details={"field": "currency"})
        moment = now or _now()
        return cls(
            id=uuid4(),
            user_id=user_id,
            package_id=package_id,
            package_slug=package_slug,
            credits=credits,
            amount_minor=amount_minor,
            currency=normalized_currency,
            idempotency_key=idempotency_key,
            created_at=moment,
            updated_at=moment,
        )

    @property
    def is_paid(self) -> bool:
        return self.status is TopUpStatus.PAID

    def attach_checkout(
        self, *, session_id: str, checkout_url: str, now: datetime | None = None
    ) -> None:
        if self.checkout_session_id and self.checkout_session_id != session_id:
            raise ValidationError("该充值单已绑定其它 Checkout Session")
        self.checkout_session_id = session_id
        self.checkout_url = checkout_url
        self.updated_at = now or _now()

    def apply_outcome(self, outcome: PaymentOutcome, *, now: datetime | None = None) -> None:
        """Apply a webhook outcome; the first terminal outcome wins."""
        if self.status is not TopUpStatus.PENDING:
            return
        self.status = TopUpStatus(outcome.value)
        self.updated_at = now or _now()
