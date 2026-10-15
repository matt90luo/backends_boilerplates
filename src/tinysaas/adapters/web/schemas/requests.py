"""Request bodies and query objects."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from tinysaas.domain.catalog.service import ExecMode
from tinysaas.domain.identity.user import Plan, Role

_NAME_MAX = 60
_SLUG_MAX = 40
_REASON_MAX = 255


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    all_sessions: bool = False


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=8, max_length=255)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=8, max_length=255)
    new_password: str = Field(min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    avatar_key: str | None = Field(default=None, max_length=500)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class StartTopUpRequest(BaseModel):
    package_slug: str = Field(min_length=1, max_length=_NAME_MAX)


class GrantCreditsRequest(BaseModel):
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=1, max_length=_REASON_MAX)


class CreateServiceRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=_SLUG_MAX)
    name: str = Field(min_length=1, max_length=80)
    credit_cost: int = Field(ge=1, le=100_000)
    exec_mode: ExecMode = ExecMode.SYNC
    description: str | None = Field(default=None, max_length=500)
    upstream_url: str | None = Field(default=None, max_length=500)
    timeout_secs: int = Field(default=30, ge=1, le=600)
    is_active: bool = True


class UpdateServiceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    credit_cost: int | None = Field(default=None, ge=1, le=100_000)
    exec_mode: ExecMode | None = None
    upstream_url: str | None = Field(default=None, max_length=500)
    clear_upstream_url: bool = False
    timeout_secs: int | None = Field(default=None, ge=1, le=600)
    is_active: bool | None = None


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    plan: Plan | None = None
    daily_quota: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None


class PresignUploadRequest(BaseModel):
    purpose: str = Field(default="artifact", max_length=32)
    content_type: str = Field(max_length=128)
    size: int = Field(ge=1)
    filename: str | None = Field(default=None, max_length=200)


class PresignDownloadRequest(BaseModel):
    key: str = Field(min_length=3, max_length=500)
    download_name: str | None = Field(default=None, max_length=200)


@dataclass(frozen=True, slots=True)
class Pagination:
    limit: int
    offset: int
