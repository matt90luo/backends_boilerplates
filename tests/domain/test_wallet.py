"""The credit protocol: reserve -> settle / refund, plus admin adjustments."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tinysaas.domain.billing.credits import CreditAmount, CreditKind
from tinysaas.domain.billing.wallet import InsufficientCredits, Wallet
from tinysaas.domain.errors import ValidationError


def funded_wallet(balance: int = 10) -> Wallet:
    wallet = Wallet.for_user(uuid4())
    wallet.top_up(CreditAmount(balance), reference="test")
    return wallet


def test_top_up_creates_a_ledger_entry() -> None:
    wallet = funded_wallet(10)

    assert wallet.balance == 10
    assert wallet.reserved == 0


def test_reserve_moves_balance_into_reserved() -> None:
    wallet = funded_wallet(10)
    invocation_id = uuid4()

    entry = wallet.reserve(CreditAmount(4), invocation_id=invocation_id)

    assert wallet.balance == 6
    assert wallet.reserved == 4
    assert entry.kind is CreditKind.RESERVE
    assert entry.amount == -4
    assert entry.balance_after == 6
    assert entry.invocation_id == invocation_id


def test_reserve_without_funds_is_rejected() -> None:
    wallet = funded_wallet(2)

    with pytest.raises(InsufficientCredits) as error:
        wallet.reserve(CreditAmount(3), invocation_id=uuid4())

    assert error.value.code == "INSUFFICIENT_CREDITS"
    assert wallet.balance == 2
    assert wallet.reserved == 0


def test_settle_consumes_the_reservation_without_changing_balance() -> None:
    wallet = funded_wallet(10)
    invocation_id = uuid4()
    wallet.reserve(CreditAmount(4), invocation_id=invocation_id)

    entry = wallet.settle(CreditAmount(4), invocation_id=invocation_id)

    assert wallet.balance == 6
    assert wallet.reserved == 0
    assert entry.kind is CreditKind.SETTLE
    assert entry.amount == 0


def test_refund_returns_credits_to_the_balance() -> None:
    wallet = funded_wallet(10)
    invocation_id = uuid4()
    wallet.reserve(CreditAmount(4), invocation_id=invocation_id)

    entry = wallet.refund(CreditAmount(4), invocation_id=invocation_id, reason="timeout")

    assert wallet.balance == 10
    assert wallet.reserved == 0
    assert entry.kind is CreditKind.REFUND
    assert entry.amount == 4


def test_settle_requires_a_matching_reservation() -> None:
    wallet = funded_wallet(10)
    with pytest.raises(ValidationError):
        wallet.settle(CreditAmount(1), invocation_id=uuid4())


def test_admin_adjustment_can_be_negative_but_never_below_zero() -> None:
    wallet = funded_wallet(5)

    entry = wallet.adjust(-3, reason="chargeback")
    assert wallet.balance == 2
    assert entry.kind is CreditKind.ADMIN_ADJUST

    with pytest.raises(InsufficientCredits):
        wallet.adjust(-5, reason="too much")
    with pytest.raises(ValidationError):
        wallet.adjust(0, reason="nothing")


def test_credit_amount_must_be_positive_integer() -> None:
    with pytest.raises(ValidationError):
        CreditAmount(0)
    with pytest.raises(ValidationError):
        CreditAmount(-1)
