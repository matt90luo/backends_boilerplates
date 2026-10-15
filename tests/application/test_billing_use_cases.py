"""Billing use cases exercised directly through the container."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from tests.conftest import AppContext
from tests.fakes.external import WEBHOOK_SIGNATURE, webhook_payload
from tinysaas.application.dto.commands import (
    GrantCreditsCommand,
    ListLedgerQuery,
    StartTopUpCommand,
)
from tinysaas.application.errors import (
    InvalidPaymentEvent,
    InvalidWebhookSignature,
    PackageNotFound,
)
from tinysaas.application.use_cases.billing import (
    GetWalletUseCase,
    GrantCreditsUseCase,
    HandleTopUpWebhookUseCase,
    ListCreditPackagesUseCase,
    ListLedgerUseCase,
    StartTopUpUseCase,
)
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.errors import Forbidden
from tinysaas.domain.identity.user import Plan, Role

pytestmark = pytest.mark.asyncio


def principal(user, *, role: Role | None = None, plan: Plan | None = None) -> Principal:  # type: ignore[no-untyped-def]
    return Principal(
        user_id=user.id,
        role=role or user.role,
        plan=plan or user.plan,
        daily_quota=user.daily_quota,
    )


async def test_list_packages_only_returns_active_ones(ctx: AppContext) -> None:
    from dataclasses import replace

    ctx.seed_package(slug="starter")
    inactive = ctx.seed_package(slug="legacy")
    ctx.store.packages[inactive.id] = replace(inactive, is_active=False)

    packages = await ListCreditPackagesUseCase(uow_factory=ctx.container.uow_factory()).execute()

    assert [package.slug for package in packages] == ["starter"]


async def test_topup_creation_is_idempotent(ctx: AppContext) -> None:
    package = ctx.seed_package(slug="starter", credits=100, amount_minor=500)
    user = ctx.seed_user(email="buyer@example.com", password="Passw0rd!23")
    use_case = StartTopUpUseCase(
        uow_factory=ctx.container.uow_factory(),
        gateway=ctx.container.payment_gateway(),
        options=ctx.container.options(),
        clock=ctx.clock,
        logger=ctx.container.logger(),
    )

    first = await use_case.execute(
        principal(user), StartTopUpCommand(package_slug="starter", idempotency_key="key-1")
    )
    second = await use_case.execute(
        principal(user), StartTopUpCommand(package_slug="starter", idempotency_key="key-1")
    )

    assert first.topup_id == second.topup_id
    assert first.reused is False
    assert second.reused is True
    assert len(ctx.gateway.sessions) == 1
    assert first.credits == package.credits
    assert first.checkout_url.endswith(str(first.topup_id))


async def test_topup_rejects_unknown_package(ctx: AppContext) -> None:
    user = ctx.seed_user(email="buyer2@example.com", password="Passw0rd!23")
    use_case = StartTopUpUseCase(
        uow_factory=ctx.container.uow_factory(),
        gateway=ctx.container.payment_gateway(),
        options=ctx.container.options(),
        clock=ctx.clock,
        logger=ctx.container.logger(),
    )

    with pytest.raises(PackageNotFound):
        await use_case.execute(
            principal(user), StartTopUpCommand(package_slug="ghost", idempotency_key="k")
        )


async def test_webhook_credits_once_even_if_replayed(ctx: AppContext) -> None:
    ctx.seed_package(slug="starter", credits=100, amount_minor=500)
    user = ctx.seed_user(email="paid@example.com", password="Passw0rd!23")
    start = StartTopUpUseCase(
        uow_factory=ctx.container.uow_factory(),
        gateway=ctx.container.payment_gateway(),
        options=ctx.container.options(),
        clock=ctx.clock,
        logger=ctx.container.logger(),
    )
    checkout = await start.execute(
        principal(user), StartTopUpCommand(package_slug="starter", idempotency_key="key-2")
    )
    payload = webhook_payload(
        event_id="evt_paid",
        topup_id=checkout.topup_id,
        session_id=f"cs_test_{checkout.topup_id}",
    )
    webhook = HandleTopUpWebhookUseCase(
        uow_factory=ctx.container.uow_factory(),
        gateway=ctx.container.payment_gateway(),
        mailer=ctx.container.mailer(),
        options=ctx.container.options(),
        clock=ctx.clock,
        logger=ctx.container.logger(),
    )

    assert await webhook.execute(payload, WEBHOOK_SIGNATURE) is True
    assert await webhook.execute(payload, WEBHOOK_SIGNATURE) is False

    assert ctx.balance_of(user.id) == 100
    assert ctx.ledger_kinds(user.id) == ["topup"]
    assert "credit_receipt" in ctx.mailer.templates()

    wallet_use_case = GetWalletUseCase(uow_factory=ctx.container.uow_factory(), clock=ctx.clock)
    wallet = await wallet_use_case.execute(principal(user))
    assert wallet.balance == 100

    ledger = await ListLedgerUseCase(uow_factory=ctx.container.uow_factory()).execute(
        principal(user), ListLedgerQuery()
    )
    assert ledger.total == 1
    assert ledger.items[0].amount == 100
    assert ledger.items[0].reference == str(checkout.topup_id)


async def test_webhook_rejects_bad_signature_and_unknown_topup(ctx: AppContext) -> None:
    ctx.seed_package(slug="starter")
    user = ctx.seed_user(email="sig@example.com", password="Passw0rd!23")
    webhook = HandleTopUpWebhookUseCase(
        uow_factory=ctx.container.uow_factory(),
        gateway=ctx.container.payment_gateway(),
        mailer=ctx.container.mailer(),
        options=ctx.container.options(),
        clock=ctx.clock,
        logger=ctx.container.logger(),
    )
    payload = webhook_payload(event_id="evt_x", topup_id=user.id, session_id="cs_x")

    with pytest.raises(InvalidWebhookSignature):
        await webhook.execute(payload, "wrong-signature")

    with pytest.raises(InvalidPaymentEvent):
        await webhook.execute(payload, WEBHOOK_SIGNATURE)


async def test_webhook_ignores_unrelated_events(ctx: AppContext) -> None:
    payload = webhook_payload(
        event_id="evt_other",
        topup_id=UUID("00000000-0000-0000-0000-000000000000"),
        session_id="cs_other",
        event_type="payment_intent.created",
    )
    webhook = HandleTopUpWebhookUseCase(
        uow_factory=ctx.container.uow_factory(),
        gateway=ctx.container.payment_gateway(),
        mailer=ctx.container.mailer(),
        options=ctx.container.options(),
        clock=ctx.clock,
        logger=ctx.container.logger(),
    )

    assert await webhook.execute(payload, WEBHOOK_SIGNATURE) is False


async def test_grant_credits_requires_admin_and_records_reason(ctx: AppContext) -> None:
    admin = ctx.seed_user(email="admin@example.com", password="Passw0rd!23", role=Role.ADMIN)
    member = ctx.seed_user(email="member@example.com", password="Passw0rd!23")
    use_case = GrantCreditsUseCase(
        uow_factory=ctx.container.uow_factory(), clock=ctx.clock, logger=ctx.container.logger()
    )

    with pytest.raises(Forbidden):
        await use_case.execute(
            principal(member),
            GrantCreditsCommand(user_id=member.id, amount=10, reason="nope"),
        )

    await use_case.execute(
        principal(admin), GrantCreditsCommand(user_id=member.id, amount=20, reason="goodwill")
    )
    entry = await use_case.execute(
        principal(admin),
        GrantCreditsCommand(user_id=member.id, amount=-5, reason="chargeback"),
    )
    assert entry.amount == -5
    assert entry.reason == "chargeback"
    assert entry.balance_after == 15
    assert ctx.balance_of(member.id) == 15
    assert ctx.ledger_kinds(member.id) == ["admin_adjust", "admin_adjust"]


async def test_wallet_is_provisioned_for_legacy_accounts(ctx: AppContext) -> None:
    admin = ctx.seed_user(email="admin2@example.com", password="Passw0rd!23", role=Role.ADMIN)
    member = ctx.seed_user(email="legacy@example.com", password="Passw0rd!23")
    ctx.store.wallets.pop(member.id)

    use_case = GrantCreditsUseCase(
        uow_factory=ctx.container.uow_factory(), clock=ctx.clock, logger=ctx.container.logger()
    )
    await use_case.execute(
        principal(admin), GrantCreditsCommand(user_id=member.id, amount=7, reason="migration")
    )

    assert ctx.balance_of(member.id) == 7


async def test_fake_clock_drives_token_expiry(ctx: AppContext) -> None:
    """Sanity check that the controllable clock is what use cases observe."""
    from tinysaas.domain.identity.session import RefreshToken

    token = RefreshToken.issue(
        user_id=ctx.seed_user(email="clock@example.com", password="Passw0rd!23").id,
        token_hash="h",
        ttl=timedelta(minutes=5),
        now=ctx.clock.now(),
    )
    ctx.clock.advance(minutes=10)
    assert token.is_active(now=ctx.clock.now()) is False
    assert isinstance(ctx.clock.now(), datetime)
