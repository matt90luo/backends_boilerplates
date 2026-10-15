"""Application level errors.

Every error exposes a stable ``code``; the web layer owns the code -> HTTP
status table so that neither the domain nor the application knows about HTTP.
"""

from __future__ import annotations

from tinysaas.domain.errors import DomainError


class ApplicationError(DomainError):
    code = "APPLICATION_ERROR"


# --- identity / auth -------------------------------------------------------
class EmailAlreadyRegistered(ApplicationError):
    code = "EMAIL_TAKEN"


class InvalidCredentials(ApplicationError):
    code = "AUTH_INVALID_CREDENTIALS"


class InvalidToken(ApplicationError):
    code = "AUTH_INVALID_TOKEN"


class TokenExpired(ApplicationError):
    code = "AUTH_TOKEN_EXPIRED"


class RefreshTokenReused(ApplicationError):
    code = "AUTH_REFRESH_REUSED"


class AuthenticationRequired(ApplicationError):
    code = "AUTH_REQUIRED"


class EmailNotVerified(ApplicationError):
    code = "EMAIL_NOT_VERIFIED"


class UserDisabled(ApplicationError):
    code = "USER_DISABLED"


class UserNotFound(ApplicationError):
    code = "USER_NOT_FOUND"


class ApiKeyNotFound(ApplicationError):
    code = "API_KEY_NOT_FOUND"


# --- catalog ---------------------------------------------------------------
class ServiceNotFound(ApplicationError):
    code = "SERVICE_NOT_FOUND"


class ServiceSlugTaken(ApplicationError):
    code = "SERVICE_SLUG_TAKEN"


class ExecModeMismatch(ApplicationError):
    code = "EXEC_MODE_MISMATCH"


class ServiceHandlerMissing(ApplicationError):
    code = "SERVICE_HANDLER_MISSING"


# --- billing ---------------------------------------------------------------
class PackageNotFound(ApplicationError):
    code = "PACKAGE_NOT_FOUND"


class TopUpNotFound(ApplicationError):
    code = "TOPUP_NOT_FOUND"


class PaymentConfigurationError(ApplicationError):
    code = "PAYMENT_CONFIGURATION_ERROR"


class PaymentProviderError(ApplicationError):
    code = "PAYMENT_PROVIDER_ERROR"


class InvalidWebhookSignature(ApplicationError):
    code = "INVALID_WEBHOOK_SIGNATURE"


class InvalidPaymentEvent(ApplicationError):
    code = "INVALID_PAYMENT_EVENT"


# --- invocation ------------------------------------------------------------
class InvocationNotFound(ApplicationError):
    code = "INVOCATION_NOT_FOUND"


class IdempotencyConflict(ApplicationError):
    code = "IDEMPOTENCY_IN_PROGRESS"


class QuotaExceeded(ApplicationError):
    code = "QUOTA_EXCEEDED"


class UpstreamFailed(ApplicationError):
    code = "UPSTREAM_FAILED"


class UpstreamTimeout(ApplicationError):
    code = "UPSTREAM_TIMEOUT"


class RateLimited(ApplicationError):
    code = "RATE_LIMITED"


# --- notifications ---------------------------------------------------------
class MailDeliveryError(ApplicationError):
    code = "MAIL_DELIVERY_FAILED"


# --- storage ---------------------------------------------------------------
class StorageError(ApplicationError):
    code = "STORAGE_ERROR"


def error_from_code(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> ApplicationError:
    """Rebuild an error from a recorded invocation (idempotent replay)."""
    error = ApplicationError(message, details=details)
    error.code = code
    return error
