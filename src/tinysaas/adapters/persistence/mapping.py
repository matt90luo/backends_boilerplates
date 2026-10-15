"""Row <-> domain entity translation."""

from __future__ import annotations

from tinysaas.adapters.persistence.models import (
    ApiKeyRow,
    CreditLedgerRow,
    CreditPackageRow,
    InvocationRow,
    OneTimeTokenRow,
    RefreshTokenRow,
    ServiceRow,
    TopUpRow,
    UserRow,
    WalletRow,
)
from tinysaas.domain.billing.credits import CreditKind, CreditLedgerEntry
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.topup import TopUp, TopUpStatus
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.catalog.service import ExecMode, Service
from tinysaas.domain.identity.api_key import ApiKey
from tinysaas.domain.identity.one_time_token import OneTimeToken, TokenKind
from tinysaas.domain.identity.session import RefreshToken
from tinysaas.domain.identity.user import Plan, Role, User
from tinysaas.domain.invocation.invocation import Invocation, InvocationStatus


# --- users -----------------------------------------------------------------
def to_user(row: UserRow) -> User:
    return User(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        role=Role(row.role),
        plan=Plan(row.plan),
        daily_quota=row.daily_quota,
        is_active=row.is_active,
        display_name=row.display_name,
        avatar_key=row.avatar_key,
        email_verified_at=row.email_verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def new_user_row(user: User) -> UserRow:
    return UserRow(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        role=user.role.value,
        plan=user.plan.value,
        daily_quota=user.daily_quota,
        is_active=user.is_active,
        display_name=user.display_name,
        avatar_key=user.avatar_key,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def apply_user(row: UserRow, user: User) -> None:
    row.email = user.email
    row.password_hash = user.password_hash
    row.role = user.role.value
    row.plan = user.plan.value
    row.daily_quota = user.daily_quota
    row.is_active = user.is_active
    row.display_name = user.display_name
    row.avatar_key = user.avatar_key
    row.email_verified_at = user.email_verified_at
    row.created_at = user.created_at
    row.updated_at = user.updated_at


# --- wallets / ledger ------------------------------------------------------
def to_wallet(row: WalletRow) -> Wallet:
    return Wallet(
        user_id=row.user_id,
        balance=row.balance,
        reserved=row.reserved,
        updated_at=row.updated_at,
    )


def new_wallet_row(wallet: Wallet) -> WalletRow:
    return WalletRow(
        user_id=wallet.user_id,
        balance=wallet.balance,
        reserved=wallet.reserved,
        updated_at=wallet.updated_at,
    )


def apply_wallet(row: WalletRow, wallet: Wallet) -> None:
    row.balance = wallet.balance
    row.reserved = wallet.reserved
    row.updated_at = wallet.updated_at


def to_ledger_entry(row: CreditLedgerRow) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        id=row.id,
        user_id=row.user_id,
        kind=CreditKind(row.kind),
        amount=row.amount,
        balance_after=row.balance_after,
        invocation_id=row.invocation_id,
        reference=row.reference,
        reason=row.reason,
        created_at=row.created_at,
    )


def new_ledger_row(entry: CreditLedgerEntry) -> CreditLedgerRow:
    return CreditLedgerRow(
        id=entry.id,
        user_id=entry.user_id,
        kind=entry.kind.value,
        amount=entry.amount,
        balance_after=entry.balance_after,
        invocation_id=entry.invocation_id,
        reference=entry.reference,
        reason=entry.reason,
        created_at=entry.created_at,
    )


# --- packages --------------------------------------------------------------
def to_credit_package(row: CreditPackageRow) -> CreditPackage:
    return CreditPackage(
        id=row.id,
        slug=row.slug,
        name=row.name,
        credits=row.credits,
        amount_minor=row.amount_minor,
        currency=row.currency,
        stripe_price_id=row.stripe_price_id,
        is_active=row.is_active,
    )


# --- services --------------------------------------------------------------
def to_service(row: ServiceRow) -> Service:
    return Service(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        credit_cost=row.credit_cost,
        exec_mode=ExecMode(row.exec_mode),
        upstream_url=row.upstream_url,
        timeout_secs=row.timeout_secs,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def new_service_row(service: Service) -> ServiceRow:
    return ServiceRow(
        id=service.id,
        slug=service.slug,
        name=service.name,
        description=service.description,
        credit_cost=service.credit_cost,
        exec_mode=service.exec_mode.value,
        upstream_url=service.upstream_url,
        timeout_secs=service.timeout_secs,
        is_active=service.is_active,
        created_at=service.created_at,
        updated_at=service.updated_at,
    )


def apply_service(row: ServiceRow, service: Service) -> None:
    row.slug = service.slug
    row.name = service.name
    row.description = service.description
    row.credit_cost = service.credit_cost
    row.exec_mode = service.exec_mode.value
    row.upstream_url = service.upstream_url
    row.timeout_secs = service.timeout_secs
    row.is_active = service.is_active
    row.updated_at = service.updated_at


# --- invocations -----------------------------------------------------------
def to_invocation(row: InvocationRow) -> Invocation:
    return Invocation(
        id=row.id,
        request_id=row.request_id,
        user_id=row.user_id,
        service_id=row.service_id,
        service_slug=row.service_slug,
        exec_mode=ExecMode(row.exec_mode),
        status=InvocationStatus(row.status),
        credit_cost=row.credit_cost,
        credits_charged=row.credits_charged,
        credits_refunded=row.credits_refunded,
        idempotency_key=row.idempotency_key,
        latency_ms=row.latency_ms,
        upstream_status=row.upstream_status,
        error_code=row.error_code,
        error_message=row.error_message,
        request_payload=row.request_payload,
        response_body=row.response_body,
        response_content_type=row.response_content_type,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def new_invocation_row(invocation: Invocation) -> InvocationRow:
    return InvocationRow(
        id=invocation.id,
        request_id=invocation.request_id,
        user_id=invocation.user_id,
        service_id=invocation.service_id,
        service_slug=invocation.service_slug,
        exec_mode=invocation.exec_mode.value,
        status=invocation.status.value,
        credit_cost=invocation.credit_cost,
        credits_charged=invocation.credits_charged,
        credits_refunded=invocation.credits_refunded,
        idempotency_key=invocation.idempotency_key,
        latency_ms=invocation.latency_ms,
        upstream_status=invocation.upstream_status,
        error_code=invocation.error_code,
        error_message=invocation.error_message,
        request_payload=invocation.request_payload,
        response_body=invocation.response_body,
        response_content_type=invocation.response_content_type,
        created_at=invocation.created_at,
        started_at=invocation.started_at,
        finished_at=invocation.finished_at,
    )


def apply_invocation(row: InvocationRow, invocation: Invocation) -> None:
    row.status = invocation.status.value
    row.credits_charged = invocation.credits_charged
    row.credits_refunded = invocation.credits_refunded
    row.latency_ms = invocation.latency_ms
    row.upstream_status = invocation.upstream_status
    row.error_code = invocation.error_code
    row.error_message = invocation.error_message
    row.request_payload = invocation.request_payload
    row.response_body = invocation.response_body
    row.response_content_type = invocation.response_content_type
    row.started_at = invocation.started_at
    row.finished_at = invocation.finished_at


# --- top ups ---------------------------------------------------------------
def to_topup(row: TopUpRow) -> TopUp:
    return TopUp(
        id=row.id,
        user_id=row.user_id,
        package_id=row.package_id,
        package_slug=row.package_slug,
        credits=row.credits,
        amount_minor=row.amount_minor,
        currency=row.currency,
        idempotency_key=row.idempotency_key,
        status=TopUpStatus(row.status),
        checkout_session_id=row.checkout_session_id,
        checkout_url=row.checkout_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def new_topup_row(topup: TopUp) -> TopUpRow:
    return TopUpRow(
        id=topup.id,
        user_id=topup.user_id,
        package_id=topup.package_id,
        package_slug=topup.package_slug,
        credits=topup.credits,
        amount_minor=topup.amount_minor,
        currency=topup.currency,
        idempotency_key=topup.idempotency_key,
        status=topup.status.value,
        checkout_session_id=topup.checkout_session_id,
        checkout_url=topup.checkout_url,
        created_at=topup.created_at,
        updated_at=topup.updated_at,
    )


def apply_topup(row: TopUpRow, topup: TopUp) -> None:
    row.status = topup.status.value
    row.checkout_session_id = topup.checkout_session_id
    row.checkout_url = topup.checkout_url
    row.updated_at = topup.updated_at


# --- sessions / credentials ------------------------------------------------
def to_refresh_token(row: RefreshTokenRow) -> RefreshToken:
    return RefreshToken(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        family_id=row.family_id,
        expires_at=row.expires_at,
        created_at=row.created_at,
        user_agent=row.user_agent,
        ip_address=row.ip_address,
        rotated_at=row.rotated_at,
        revoked_at=row.revoked_at,
    )


def new_refresh_token_row(token: RefreshToken) -> RefreshTokenRow:
    return RefreshTokenRow(
        id=token.id,
        user_id=token.user_id,
        token_hash=token.token_hash,
        family_id=token.family_id,
        expires_at=token.expires_at,
        created_at=token.created_at,
        user_agent=token.user_agent,
        ip_address=token.ip_address,
        rotated_at=token.rotated_at,
        revoked_at=token.revoked_at,
    )


def apply_refresh_token(row: RefreshTokenRow, token: RefreshToken) -> None:
    row.rotated_at = token.rotated_at
    row.revoked_at = token.revoked_at


def to_api_key(row: ApiKeyRow) -> ApiKey:
    return ApiKey(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        prefix=row.prefix,
        key_hash=row.key_hash,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def new_api_key_row(api_key: ApiKey) -> ApiKeyRow:
    return ApiKeyRow(
        id=api_key.id,
        user_id=api_key.user_id,
        name=api_key.name,
        prefix=api_key.prefix,
        key_hash=api_key.key_hash,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
    )


def apply_api_key(row: ApiKeyRow, api_key: ApiKey) -> None:
    row.last_used_at = api_key.last_used_at
    row.revoked_at = api_key.revoked_at


def to_one_time_token(row: OneTimeTokenRow) -> OneTimeToken:
    return OneTimeToken(
        id=row.id,
        user_id=row.user_id,
        kind=TokenKind(row.kind),
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        created_at=row.created_at,
        used_at=row.used_at,
    )


def new_one_time_token_row(token: OneTimeToken) -> OneTimeTokenRow:
    return OneTimeTokenRow(
        id=token.id,
        user_id=token.user_id,
        kind=token.kind.value,
        token_hash=token.token_hash,
        expires_at=token.expires_at,
        created_at=token.created_at,
        used_at=token.used_at,
    )


def apply_one_time_token(row: OneTimeTokenRow, token: OneTimeToken) -> None:
    row.used_at = token.used_at
