"""Plain configuration value objects consumed by use cases.

The container builds these from the infrastructure ``Settings`` so that the
application layer never imports pydantic-settings or reads environment
variables itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionOptions:
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    email_verification_ttl_seconds: int
    password_reset_ttl_seconds: int
    api_key_ttl_days: int
    require_email_verification: bool
    verify_email_url_template: str
    reset_password_url_template: str

    def verify_email_url(self, token: str) -> str:
        return self.verify_email_url_template.format(token=token)

    def reset_password_url(self, token: str) -> str:
        return self.reset_password_url_template.format(token=token)


@dataclass(frozen=True, slots=True)
class NotificationOptions:
    app_name: str
    support_email: str | None = None


@dataclass(frozen=True, slots=True)
class UploadOptions:
    allowed_content_types: tuple[str, ...]
    max_upload_bytes: int
    presign_ttl_seconds: int
    allow_artifact_download_for_admin: bool = True


@dataclass(frozen=True, slots=True)
class RateLimitOptions:
    enabled: bool
    login_per_minute: int
    register_per_hour: int
    password_reset_per_15_minutes: int
    service_per_minute: int


@dataclass(frozen=True, slots=True)
class BillingOptions:
    checkout_success_url: str
    checkout_cancel_url: str


@dataclass(frozen=True, slots=True)
class AppOptions:
    session: SessionOptions
    notification: NotificationOptions
    upload: UploadOptions
    rate_limit: RateLimitOptions
    billing: BillingOptions
