"""Credit value object and ledger entry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from tinysaas.domain.errors import ValidationError


class CreditKind(StrEnum):
    """Why the wallet balance changed."""

    TOPUP = "topup"
    RESERVE = "reserve"
    SETTLE = "settle"
    REFUND = "refund"
    ADMIN_ADJUST = "admin_adjust"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CreditAmount:
    """A strictly positive amount of credits."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise ValidationError("credit 数量必须是整数", details={"field": "credits"})
        if self.value <= 0:
            raise ValidationError("credit 数量必须大于 0", details={"field": "credits"})

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class CreditLedgerEntry:
    """An immutable record of one balance change.

    ``amount`` is signed (positive adds credits, negative removes them) and
    ``balance_after`` is the wallet balance after this entry was applied. A
    ``SETTLE`` entry carries ``amount == 0`` because the money already left the
    spendable balance when the reservation was taken; it only closes it.
    """

    id: UUID
    user_id: UUID
    kind: CreditKind
    amount: int
    balance_after: int
    created_at: datetime
    invocation_id: UUID | None = None
    reference: str | None = None
    reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        kind: CreditKind,
        amount: int,
        balance_after: int,
        invocation_id: UUID | None = None,
        reference: str | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        if amount == 0 and kind is not CreditKind.SETTLE:
            raise ValidationError("流水金额不能为 0", details={"field": "amount"})
        if balance_after < 0:
            raise ValidationError("钱包余额不能为负", details={"field": "balance"})
        return cls(
            id=uuid4(),
            user_id=user_id,
            kind=kind,
            amount=amount,
            balance_after=balance_after,
            created_at=now or _now(),
            invocation_id=invocation_id,
            reference=reference,
            reason=reason,
        )
