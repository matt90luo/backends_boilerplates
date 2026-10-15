"""Response payloads projected from the application DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from tinysaas.adapters.web.schemas.envelope import Payload
from tinysaas.domain.billing.credits import CreditKind
from tinysaas.domain.billing.topup import TopUpStatus
from tinysaas.domain.catalog.service import ExecMode
from tinysaas.domain.identity.user import Plan, Role
from tinysaas.domain.invocation.invocation import InvocationStatus


class UserPayload(Payload):
    id: UUID
    email: str
    role: Role
    plan: Plan
    daily_quota: int
    is_active: bool
    display_name: str | None
    avatar_key: str | None
    email_verified: bool
    created_at: datetime


class AuthSessionPayload(Payload):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    user: UserPayload


class SessionPayload(Payload):
    id: UUID
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None


class ApiKeyPayload(Payload):
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked: bool


class ApiKeyIssuedPayload(Payload):
    api_key: ApiKeyPayload
    plaintext: str


class WalletPayload(Payload):
    user_id: UUID
    balance: int
    reserved: int
    updated_at: datetime


class LedgerEntryPayload(Payload):
    id: UUID
    kind: CreditKind
    amount: int
    balance_after: int
    created_at: datetime
    invocation_id: UUID | None
    reference: str | None
    reason: str | None


class PackagePayload(Payload):
    id: UUID
    slug: str
    name: str
    credits: int
    amount_minor: int
    currency: str


class TopUpPayload(Payload):
    id: UUID
    package_slug: str
    credits: int
    amount_minor: int
    currency: str
    status: TopUpStatus
    checkout_url: str | None
    created_at: datetime


class ServicePayload(Payload):
    id: UUID
    slug: str
    name: str
    description: str | None
    credit_cost: int
    exec_mode: ExecMode
    upstream_url: str | None
    timeout_secs: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InvocationPayload(Payload):
    id: UUID
    request_id: str
    user_id: UUID
    service_slug: str
    exec_mode: ExecMode
    status: InvocationStatus
    credit_cost: int
    credits_charged: int
    credits_refunded: int
    latency_ms: int | None
    upstream_status: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class AdminUserPayload(Payload):
    user: UserPayload
    balance: int
    reserved: int


class PresignedUploadPayload(Payload):
    key: str
    url: str
    expires_in: int
    max_bytes: int
    content_type: str


class PresignedDownloadPayload(Payload):
    key: str
    url: str
    expires_in: int


class HealthPayload(Payload):
    status: str
    components: dict[str, str]


class CheckoutPayload(Payload):
    topup_id: UUID
    status: TopUpStatus
    checkout_url: str
    credits: int
    amount_minor: int
    currency: str
    reused: bool


class TaskPayload(Payload):
    task_id: UUID
    service_slug: str
    status: InvocationStatus
    credit_cost: int
    created_at: datetime
    replayed: bool
