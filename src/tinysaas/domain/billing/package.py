"""Credit packages: the products a user can buy with Stripe Checkout."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tinysaas.domain.errors import ValidationError


@dataclass(frozen=True, slots=True)
class CreditPackage:
    """Immutable catalogue entry (configuration, not a mutable aggregate)."""

    id: UUID
    slug: str
    name: str
    credits: int
    amount_minor: int
    currency: str
    stripe_price_id: str
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.slug or not self.slug.strip():
            raise ValidationError("套餐 slug 不能为空", details={"field": "slug"})
        if not self.name or not self.name.strip():
            raise ValidationError("套餐名称不能为空", details={"field": "name"})
        if self.credits <= 0:
            raise ValidationError("套餐 credit 数量必须大于 0", details={"field": "credits"})
        if self.amount_minor <= 0:
            raise ValidationError("套餐金额必须大于 0", details={"field": "amount_minor"})
        currency = self.currency.strip().lower()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("货币必须是三位 ISO 代码", details={"field": "currency"})
        if not self.stripe_price_id:
            raise ValidationError("套餐缺少 Stripe Price ID", details={"field": "stripe_price_id"})

    @property
    def unit_amount_minor(self) -> float:
        """Informational only; the checkout amount always comes from Stripe."""
        return self.amount_minor / self.credits
