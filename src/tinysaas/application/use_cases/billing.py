"""Credit wallet, top-up and Stripe webhook use cases."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from tinysaas.application.dto.billing import (
    CheckoutView,
    LedgerEntryView,
    PackageView,
    TopUpView,
    WalletView,
)
from tinysaas.application.dto.commands import (
    GrantCreditsCommand,
    ListLedgerQuery,
    StartTopUpCommand,
)
from tinysaas.application.dto.common import Page
from tinysaas.application.errors import (
    InvalidPaymentEvent,
    PackageNotFound,
    TopUpNotFound,
    UserNotFound,
)
from tinysaas.application.options import AppOptions
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.external import EmailMessage, Mailer, PaymentGateway
from tinysaas.application.ports.observability import AppLogger
from tinysaas.application.ports.persistence import UnitOfWork, UnitOfWorkFactory
from tinysaas.domain.access.policy import AccessPolicy, Principal
from tinysaas.domain.billing.credits import CreditAmount
from tinysaas.domain.billing.topup import PaymentOutcome, TopUp, TopUpStatus
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.errors import ValidationError


async def ensure_wallet(uow: UnitOfWork, user_id: UUID, *, now: datetime) -> Wallet:
    """Load the wallet, provisioning it for accounts created before wallets existed."""
    wallet = await uow.wallets.get_for_update(user_id)
    if wallet is not None:
        return wallet
    wallet = Wallet.for_user(user_id, now=now)
    await uow.wallets.add(wallet)
    return wallet


class ListCreditPackagesUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self) -> list[PackageView]:
        async with self._uow_factory() as uow:
            packages = await uow.packages.list_active()
        return [PackageView.from_package(package) for package in packages]


class GetWalletUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal) -> WalletView:
        async with self._uow_factory() as uow:
            wallet = await ensure_wallet(uow, principal.user_id, now=self._clock.now())
            await uow.commit()
        return WalletView.from_wallet(wallet)


class ListLedgerUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, query: ListLedgerQuery) -> Page[LedgerEntryView]:
        async with self._uow_factory() as uow:
            entries, total = await uow.ledger.list_for_user(
                principal.user_id, limit=query.limit, offset=query.offset
            )
        page = Page(
            items=[LedgerEntryView.from_entry(entry) for entry in entries],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
        return page


class StartTopUpUseCase:
    """Create a Stripe Checkout Session for a credit package.

    Kept idempotent: the same ``Idempotency-Key`` returns the same session, and
    the Stripe call itself uses the top-up id as its idempotency key.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        gateway: PaymentGateway,
        options: AppOptions,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._gateway = gateway
        self._options = options
        self._clock = clock
        self._logger = logger

    async def execute(self, principal: Principal, command: StartTopUpCommand) -> CheckoutView:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            package = await uow.packages.get_by_slug(command.package_slug)
            if package is None or not package.is_active:
                raise PackageNotFound("充值套餐不存在")
            proposed = TopUp.create(
                user_id=principal.user_id,
                package_id=package.id,
                package_slug=package.slug,
                credits=package.credits,
                amount_minor=package.amount_minor,
                currency=package.currency,
                idempotency_key=command.idempotency_key,
                now=now,
            )
            topup, _ = await uow.topups.add_or_get(proposed)
            await uow.commit()

        if topup.checkout_url:
            return self._reused(topup)

        price = await self._gateway.get_price(package.stripe_price_id)
        if price.amount_minor != topup.amount_minor or price.currency != topup.currency:
            self._logger.warning(
                "package_price_mismatch",
                package_slug=package.slug,
                configured_minor=topup.amount_minor,
                stripe_minor=price.amount_minor,
            )
        session = await self._gateway.create_checkout_session(
            package=package,
            user_id=principal.user_id,
            topup_id=topup.id,
            success_url=self._options.billing.checkout_success_url,
            cancel_url=self._options.billing.checkout_cancel_url,
            idempotency_key=str(topup.id),
        )
        topup.attach_checkout(session_id=session.session_id, checkout_url=session.url, now=now)
        async with self._uow_factory() as uow:
            await uow.topups.update(topup)
            await uow.commit()
        self._logger.info("topup_checkout_created", topup_id=str(topup.id))
        return CheckoutView(
            topup_id=topup.id,
            status=topup.status,
            checkout_url=session.url,
            credits=topup.credits,
            amount_minor=topup.amount_minor,
            currency=topup.currency,
        )

    @staticmethod
    def _reused(topup: TopUp) -> CheckoutView:
        assert topup.checkout_url is not None  # narrowed by the caller
        return CheckoutView(
            topup_id=topup.id,
            status=topup.status,
            checkout_url=topup.checkout_url,
            credits=topup.credits,
            amount_minor=topup.amount_minor,
            currency=topup.currency,
            reused=True,
        )


class HandleTopUpWebhookUseCase:
    """Settle a paid Checkout Session exactly once and credit the wallet."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        gateway: PaymentGateway,
        mailer: Mailer,
        options: AppOptions,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._gateway = gateway
        self._mailer = mailer
        self._options = options
        self._clock = clock
        self._logger = logger

    async def execute(self, payload: bytes, signature: str) -> bool:
        event = self._gateway.parse_webhook(payload, signature)
        if event is None:
            return False

        now = self._clock.now()
        receipt: tuple[str, int, int, str] | None = None
        async with self._uow_factory() as uow:
            fresh = await uow.processed_events.add_if_new(
                event_id=event.event_id,
                event_type=event.event_type,
                reference=str(event.topup_id),
            )
            if not fresh:
                return False
            topup = await uow.topups.get(event.topup_id)
            if topup is None:
                raise InvalidPaymentEvent("Stripe 事件引用了未知的充值单")
            if topup.checkout_session_id and topup.checkout_session_id != event.checkout_session_id:
                raise InvalidPaymentEvent("Checkout Session 与充值单不匹配")
            if event.outcome is None:
                await uow.commit()
                return False

            was_pending = topup.status is TopUpStatus.PENDING
            topup.apply_outcome(event.outcome, now=now)
            if topup.is_paid and was_pending:
                wallet = await ensure_wallet(uow, topup.user_id, now=now)
                entry = wallet.top_up(CreditAmount(topup.credits), reference=str(topup.id), now=now)
                await uow.wallets.update(wallet)
                await uow.ledger.add(entry)
                user = await uow.users.get(topup.user_id)
                if user is None:
                    raise UserNotFound("用户不存在")
                receipt = (user.email, topup.credits, topup.amount_minor, topup.currency)
            await uow.topups.update(topup)
            await uow.commit()

        if receipt is not None:
            await self._send_receipt(*receipt)
        self._logger.info(
            "topup_webhook_processed", topup_id=str(event.topup_id), outcome=event.event_type
        )
        return True

    async def _send_receipt(
        self, email: str, credits: int, amount_minor: int, currency: str
    ) -> None:
        try:
            await self._mailer.send(
                EmailMessage(
                    to=email,
                    subject=f"充值成功 · {self._options.notification.app_name}",
                    template="credit_receipt",
                    context={
                        "app_name": self._options.notification.app_name,
                        "support_email": self._options.notification.support_email,
                        "credits": credits,
                        "amount": f"{amount_minor / 100:.2f} {currency.upper()}",
                    },
                )
            )
        except Exception as error:  # pragma: no cover - delivery is best effort
            self._logger.warning(
                "email_delivery_failed", template="credit_receipt", error=str(error)
            )


class GetTopUpUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, topup_id: UUID) -> TopUpView:
        async with self._uow_factory() as uow:
            topup = await uow.topups.get(topup_id)
        if topup is None or (topup.user_id != principal.user_id and not principal.is_admin):
            raise TopUpNotFound("充值单不存在")
        return TopUpView.from_topup(topup)


class GrantCreditsUseCase:
    """Administrative credit adjustment (positive or negative)."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock, logger: AppLogger) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._logger = logger

    async def execute(self, principal: Principal, command: GrantCreditsCommand) -> LedgerEntryView:
        AccessPolicy.ensure_admin(principal)
        reason = command.reason.strip()
        if not reason:
            raise ValidationError("必须说明调整原因", details={"field": "reason"})
        now = self._clock.now()
        async with self._uow_factory() as uow:
            user = await uow.users.get(command.user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            wallet = await ensure_wallet(uow, command.user_id, now=now)
            entry = wallet.adjust(command.amount, reason=reason, now=now)
            await uow.wallets.update(wallet)
            await uow.ledger.add(entry)
            await uow.commit()
        self._logger.info(
            "credits_adjusted",
            actor_id=str(principal.user_id),
            target_user_id=str(command.user_id),
            amount=command.amount,
        )
        return LedgerEntryView.from_entry(entry)


__all__ = [
    "GrantCreditsUseCase",
    "GetTopUpUseCase",
    "GetWalletUseCase",
    "HandleTopUpWebhookUseCase",
    "ListCreditPackagesUseCase",
    "ListLedgerUseCase",
    "PaymentOutcome",
    "StartTopUpUseCase",
    "ensure_wallet",
]
