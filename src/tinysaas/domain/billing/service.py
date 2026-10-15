"""Domain service coordinating wallet, ledger and invocation."""

from __future__ import annotations

from datetime import datetime

from tinysaas.domain.billing.credits import CreditAmount, CreditLedgerEntry
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.invocation.invocation import Invocation


class CreditReservationService:
    """Two phase credit protocol: reserve -> settle or refund.

    The rules span three aggregates (wallet, ledger entry, invocation) which is
    exactly why they live in a domain service instead of leaking into the
    application layer as procedural code.
    """

    def reserve(
        self, *, wallet: Wallet, invocation: Invocation, now: datetime | None = None
    ) -> CreditLedgerEntry:
        """Freeze the credits.

        The caller decides the next status transition (``RUNNING`` for a
        synchronous call, ``QUEUED`` for a task) so that this service only owns
        the money movement.
        """
        amount = CreditAmount(invocation.credit_cost)
        return wallet.reserve(amount, invocation_id=invocation.id, now=now)

    def settle(
        self,
        *,
        wallet: Wallet,
        invocation: Invocation,
        latency_ms: int,
        upstream_status: int | None = None,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        """Consume the reservation and mark the call as paid for."""
        amount = CreditAmount(invocation.credit_cost)
        entry = wallet.settle(amount, invocation_id=invocation.id, now=now)
        invocation.mark_succeeded(latency_ms=latency_ms, upstream_status=upstream_status, now=now)
        return entry

    def refund(
        self,
        *,
        wallet: Wallet,
        invocation: Invocation,
        error_code: str,
        error_message: str,
        latency_ms: int | None = None,
        upstream_status: int | None = None,
        now: datetime | None = None,
    ) -> CreditLedgerEntry:
        amount = CreditAmount(invocation.credit_cost)
        entry = wallet.refund(amount, invocation_id=invocation.id, reason=error_code, now=now)
        invocation.mark_failed(
            error_code=error_code,
            error_message=error_message,
            refunded=True,
            latency_ms=latency_ms,
            upstream_status=upstream_status,
            now=now,
        )
        return entry
