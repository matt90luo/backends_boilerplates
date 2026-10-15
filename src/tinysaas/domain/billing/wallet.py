"""Credit wallet aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from tinysaas.domain.billing.credits import CreditAmount, CreditKind, CreditLedgerEntry
from tinysaas.domain.errors import DomainError, ValidationError


class InsufficientCredits(DomainError):
    code = "INSUFFICIENT_CREDITS"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Wallet:
    """Holds the spendable balance and the amount currently reserved.

    Invariant: ``balance >= 0``, ``reserved >= 0`` and every change is
    accompanied by a ledger entry (see :class:`CreditReservationService`).
    """

    user_id: UUID
    balance: int = 0
    reserved: int = 0
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def for_user(cls, user_id: UUID, *, now: datetime | None = None) -> Wallet:
        return cls(user_id=user_id, updated_at=now or _now())

    @property
    def available(self) -> int:
        """Credits that can be reserved right now."""
        return self.balance

    def can_afford(self, amount: CreditAmount) -> bool:
        return self.balance >= amount.value

    def top_up(
        self,
        amount: CreditAmount,
        *,
        reference: str | None = None,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        self.balance += amount.value
        self._touch(now)
        return self._entry(CreditKind.TOPUP, amount.value, reference=reference, now=now)

    def reserve(
        self,
        amount: CreditAmount,
        *,
        invocation_id: UUID,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        if not self.can_afford(amount):
            raise InsufficientCredits(
                "credit 余额不足",
                details={"required": amount.value, "balance": self.balance},
            )
        self.balance -= amount.value
        self.reserved += amount.value
        self._touch(now)
        return self._entry(CreditKind.RESERVE, -amount.value, invocation_id=invocation_id, now=now)

    def settle(
        self,
        amount: CreditAmount,
        *,
        invocation_id: UUID,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        """Consume a reservation after a successful call."""
        self._release_reservation(amount, invocation_id=invocation_id)
        self._touch(now)
        return self._entry(CreditKind.SETTLE, 0, invocation_id=invocation_id, now=now)

    def refund(
        self,
        amount: CreditAmount,
        *,
        invocation_id: UUID,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        """Return a reservation to the spendable balance after a failure."""
        self._release_reservation(amount, invocation_id=invocation_id)
        self.balance += amount.value
        self._touch(now)
        return self._entry(
            CreditKind.REFUND, amount.value, invocation_id=invocation_id, reason=reason, now=now
        )

    def adjust(self, amount: int, *, reason: str, now: datetime | None = None) -> CreditLedgerEntry:
        """Administrative adjustment; *amount* may be negative."""
        if amount == 0:
            raise ValidationError("调整数量不能为 0", details={"field": "amount"})
        if self.balance + amount < 0:
            raise InsufficientCredits(
                "调整后余额不能为负",
                details={"balance": self.balance, "amount": amount},
            )
        self.balance += amount
        self._touch(now)
        return self._entry(CreditKind.ADMIN_ADJUST, amount, reason=reason, now=now)

    def _release_reservation(self, amount: CreditAmount, *, invocation_id: UUID) -> None:
        if self.reserved < amount.value:
            raise ValidationError(
                "预扣额度与钱包状态不一致",
                details={
                    "reserved": self.reserved,
                    "amount": amount.value,
                    "invocation_id": str(invocation_id),
                },
            )
        self.reserved -= amount.value

    def _entry(
        self,
        kind: CreditKind,
        amount: int,
        *,
        invocation_id: UUID | None = None,
        reference: str | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        return CreditLedgerEntry.create(
            user_id=self.user_id,
            kind=kind,
            amount=amount,
            balance_after=self.balance,
            invocation_id=invocation_id,
            reference=reference,
            reason=reason,
            now=now,
        )

    def _touch(self, now: datetime | None = None) -> None:
        self.updated_at = now or _now()
