"""Billing DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tinysaas.domain.billing.credits import CreditKind, CreditLedgerEntry
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import TopUp, TopUpStatus
from tinysaas.domain.billing.wallet import Wallet


@dataclass(frozen=True, slots=True)
class WalletView:
    user_id: UUID
    balance: int
    reserved: int
    updated_at: datetime

    @classmethod
    def from_wallet(cls, wallet: Wallet) -> WalletView:
        return cls(
            user_id=wallet.user_id,
            balance=wallet.balance,
            reserved=wallet.reserved,
            updated_at=wallet.updated_at,
        )


@dataclass(frozen=True, slots=True)
class LedgerEntryView:
    id: UUID
    kind: CreditKind
    amount: int
    balance_after: int
    created_at: datetime
    invocation_id: UUID | None
    reference: str | None
    reason: str | None

    @classmethod
    def from_entry(cls, entry: CreditLedgerEntry) -> LedgerEntryView:
        return cls(
            id=entry.id,
            kind=entry.kind,
            amount=entry.amount,
            balance_after=entry.balance_after,
            created_at=entry.created_at,
            invocation_id=entry.invocation_id,
            reference=entry.reference,
            reason=entry.reason,
        )


@dataclass(frozen=True, slots=True)
class PackageView:
    id: UUID
    slug: str
    name: str
    credits: int
    amount_minor: int
    currency: str

    @classmethod
    def from_package(cls, package: CreditPackage) -> PackageView:
        return cls(
            id=package.id,
            slug=package.slug,
            name=package.name,
            credits=package.credits,
            amount_minor=package.amount_minor,
            currency=package.currency,
        )


@dataclass(frozen=True, slots=True)
class TopUpView:
    id: UUID
    package_slug: str
    credits: int
    amount_minor: int
    currency: str
    status: TopUpStatus
    checkout_url: str | None
    created_at: datetime

    @classmethod
    def from_topup(cls, topup: TopUp) -> TopUpView:
        return cls(
            id=topup.id,
            package_slug=topup.package_slug,
            credits=topup.credits,
            amount_minor=topup.amount_minor,
            currency=topup.currency,
            status=topup.status,
            checkout_url=topup.checkout_url,
            created_at=topup.created_at,
        )


@dataclass(frozen=True, slots=True)
class CheckoutView:
    """Result of ``POST /billing/checkout``."""

    topup_id: UUID
    status: TopUpStatus
    checkout_url: str
    credits: int
    amount_minor: int
    currency: str
    reused: bool = False
