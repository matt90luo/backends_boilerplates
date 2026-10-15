"""Commands and queries: what the API hands to a use case.

The web layer validates *shape* (types, lengths) with Pydantic and then builds
these objects; semantic validation stays in the domain and the use cases.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from tinysaas.domain.access.policy import Principal
from tinysaas.domain.catalog.service import ExecMode
from tinysaas.domain.identity.user import Plan, Role
from tinysaas.domain.invocation.invocation import InvocationStatus


# --- identity --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    email: str
    password: str
    display_name: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True, slots=True)
class LoginCommand:
    email: str
    password: str
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshSessionCommand:
    refresh_token: str
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class LogoutCommand:
    refresh_token: str


@dataclass(frozen=True, slots=True)
class Credentials:
    """Raw credentials extracted from the request by the middleware."""

    scheme: str
    value: str
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True, slots=True)
class VerifyEmailCommand:
    token: str


@dataclass(frozen=True, slots=True)
class RequestPasswordResetCommand:
    email: str


@dataclass(frozen=True, slots=True)
class ResetPasswordCommand:
    token: str
    new_password: str


@dataclass(frozen=True, slots=True)
class UpdateProfileCommand:
    display_name: str | None = None
    avatar_key: str | None = None


@dataclass(frozen=True, slots=True)
class ChangePasswordCommand:
    current_password: str
    new_password: str


@dataclass(frozen=True, slots=True)
class CreateApiKeyCommand:
    name: str
    expires_in_days: int | None = None


# --- billing ---------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StartTopUpCommand:
    package_slug: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ListLedgerQuery:
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class GrantCreditsCommand:
    user_id: UUID
    amount: int
    reason: str


# --- catalog ---------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CreateServiceCommand:
    slug: str
    name: str
    credit_cost: int
    exec_mode: ExecMode = ExecMode.SYNC
    description: str | None = None
    upstream_url: str | None = None
    timeout_secs: int = 30
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class UpdateServiceCommand:
    name: str | None = None
    description: str | None = None
    credit_cost: int | None = None
    exec_mode: ExecMode | None = None
    upstream_url: str | None = None
    clear_upstream_url: bool = False
    timeout_secs: int | None = None
    is_active: bool | None = None


@dataclass(frozen=True, slots=True)
class ListServicesQuery:
    include_inactive: bool = False
    limit: int = 50
    offset: int = 0


# --- invocations -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ExecuteServiceCommand:
    principal: Principal
    service_slug: str
    payload: bytes = b""
    content_type: str = "application/json"
    headers: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str | None = None
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class SubmitServiceTaskCommand:
    principal: Principal
    service_slug: str
    payload: bytes = b""
    content_type: str = "application/json"
    idempotency_key: str | None = None
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class ListInvocationsQuery:
    limit: int = 50
    offset: int = 0
    status: InvocationStatus | None = None
    service_slug: str | None = None


@dataclass(frozen=True, slots=True)
class ListUserInvocationsQuery(ListInvocationsQuery):
    user_id: UUID | None = None


# --- administration --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ListUsersQuery:
    search: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class UpdateUserCommand:
    role: Role | None = None
    plan: Plan | None = None
    daily_quota: int | None = None
    is_active: bool | None = None


# --- files -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PresignUploadCommand:
    purpose: str
    content_type: str
    size: int
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class PresignDownloadQuery:
    key: str
    download_name: str | None = None
