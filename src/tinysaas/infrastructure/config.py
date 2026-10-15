"""Environment driven configuration (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from tinysaas.application.options import (
    AppOptions,
    BillingOptions,
    NotificationOptions,
    RateLimitOptions,
    SessionOptions,
    UploadOptions,
)

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:5173"
DEFAULT_UPLOAD_TYPES = (
    "image/png,image/jpeg,image/webp,image/gif,application/pdf,"
    "application/json,text/csv,text/plain,application/zip"
)


class Settings(BaseSettings):
    """All runtime configuration in one place (see ``.env.example``)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- application ---
    environment: Literal["local", "staging", "production", "test"] = "local"
    log_level: str = "INFO"
    log_json: bool | None = None
    api_prefix: str = "/api/v1"
    public_base_url: str = "http://localhost:3000"
    cors_allow_origins: str = DEFAULT_CORS_ORIGINS
    trusted_proxies: str = ""

    # --- database ---
    database_url: str = "postgresql+asyncpg://postgres:postgres_strong_pass@127.0.0.1:5432/tests"
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5

    # --- redis ---
    redis_url: str = "redis://:redis_strong_pass@127.0.0.1:6379/0"

    # --- object storage (S3 compatible / RustFS) ---
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str = "RUSTFSadmin"
    s3_secret_key: str = "RUSTFS_strong_pass"
    s3_bucket: str = "tinysaas"
    s3_use_path_style: bool = True
    s3_auto_create_bucket: bool = True
    storage_backend: Literal["s3", "memory"] = "s3"

    # --- security ---
    jwt_secret_key: str = "dev-insecure-change-me-please-32-bytes-min"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "tinysaas"
    jwt_audience: str = "tinysaas-clients"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 2_592_000
    email_verification_ttl_seconds: int = 86_400
    password_reset_ttl_seconds: int = 1_800
    api_key_ttl_days: int = 365
    api_key_prefix: str = "tsk"
    require_email_verification: bool = False
    refresh_transport: Literal["body", "cookie"] = "body"
    refresh_cookie_name: str = "ts_refresh"
    refresh_cookie_secure: bool = False
    refresh_cookie_path: str = "/"
    argon2_time_cost: int = 2
    argon2_memory_cost: int = 65_536
    argon2_parallelism: int = 2

    # --- payments ---
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_success_url: str = "http://localhost:3000/checkout/success"
    stripe_cancel_url: str = "http://localhost:3000/checkout/cancel"
    stripe_price_starter: str = "price_replace_me_starter"
    stripe_price_pro: str = "price_replace_me_pro"
    stripe_price_scale: str = "price_replace_me_scale"

    # --- email ---
    mailer: Literal["console", "resend"] = "console"
    mail_from: str = "Tiny SaaS <no-reply@tinysaas.local>"
    mail_outbox_dir: str = "var/mail"
    resend_api_key: str = ""
    resend_base_url: str = "https://api.resend.com"
    app_name: str = "Tiny SaaS"
    support_email: str = "support@tinysaas.local"

    # --- rate limiting ---
    rate_limit_enabled: bool = True
    rate_limit_login_per_minute: int = 5
    rate_limit_register_per_hour: int = 10
    rate_limit_password_reset_per_15_minutes: int = 3
    rate_limit_service_per_minute: int = 60

    # --- uploads ---
    upload_allowed_content_types: str = DEFAULT_UPLOAD_TYPES
    upload_max_bytes: int = 5_242_880
    presign_ttl_seconds: int = 900

    # --- observability ---
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    # --- demo / seeding ---
    demo_executor_enabled: bool = True
    http_proxy_timeout_seconds: int = 60
    admin_email: str = "admin@tinysaas.local"
    admin_password: str = "admin12345"

    # --- derived helpers ---------------------------------------------------
    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

    @property
    def proxy_hosts(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxies.split(",") if item.strip()]

    @property
    def allowed_upload_types(self) -> tuple[str, ...]:
        return tuple(
            item.strip() for item in self.upload_allowed_content_types.split(",") if item.strip()
        )

    @property
    def json_logs(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return self.environment not in {"local", "test"}

    def build_app_options(self) -> AppOptions:
        """Translate infrastructure settings into application value objects."""
        return AppOptions(
            session=SessionOptions(
                access_token_ttl_seconds=self.access_token_ttl_seconds,
                refresh_token_ttl_seconds=self.refresh_token_ttl_seconds,
                email_verification_ttl_seconds=self.email_verification_ttl_seconds,
                password_reset_ttl_seconds=self.password_reset_ttl_seconds,
                api_key_ttl_days=self.api_key_ttl_days,
                require_email_verification=self.require_email_verification,
                verify_email_url_template=(
                    f"{self.public_base_url.rstrip('/')}/verify-email?token={{token}}"
                ),
                reset_password_url_template=(
                    f"{self.public_base_url.rstrip('/')}/reset-password?token={{token}}"
                ),
            ),
            notification=NotificationOptions(
                app_name=self.app_name, support_email=self.support_email or None
            ),
            upload=UploadOptions(
                allowed_content_types=self.allowed_upload_types,
                max_upload_bytes=self.upload_max_bytes,
                presign_ttl_seconds=self.presign_ttl_seconds,
            ),
            rate_limit=RateLimitOptions(
                enabled=self.rate_limit_enabled,
                login_per_minute=self.rate_limit_login_per_minute,
                register_per_hour=self.rate_limit_register_per_hour,
                password_reset_per_15_minutes=self.rate_limit_password_reset_per_15_minutes,
                service_per_minute=self.rate_limit_service_per_minute,
            ),
            billing=BillingOptions(
                checkout_success_url=self.stripe_success_url,
                checkout_cancel_url=self.stripe_cancel_url,
            ),
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor used by the container and Alembic."""
    return Settings()
