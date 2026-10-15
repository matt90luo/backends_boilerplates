"""Error code -> HTTP status mapping and the global exception handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from tinysaas.application.ports.observability import Telemetry
from tinysaas.domain.errors import DomainError

_STATUS_BY_CODE: dict[str, int] = {
    # validation / conflict
    "VALIDATION_ERROR": 422,
    "WEAK_PASSWORD": 422,
    "CONFLICT": 409,
    "EMAIL_TAKEN": 409,
    "SERVICE_SLUG_TAKEN": 409,
    "EXEC_MODE_MISMATCH": 409,
    "SERVICE_INACTIVE": 409,
    "IDEMPOTENCY_IN_PROGRESS": 409,
    # auth
    "AUTH_REQUIRED": 401,
    "AUTH_INVALID_CREDENTIALS": 401,
    "AUTH_INVALID_TOKEN": 401,
    "AUTH_TOKEN_EXPIRED": 401,
    "AUTH_REFRESH_REUSED": 401,
    "FORBIDDEN": 403,
    "USER_DISABLED": 403,
    "EMAIL_NOT_VERIFIED": 403,
    # not found
    "NOT_FOUND": 404,
    "USER_NOT_FOUND": 404,
    "SERVICE_NOT_FOUND": 404,
    "INVOCATION_NOT_FOUND": 404,
    "TOPUP_NOT_FOUND": 404,
    "PACKAGE_NOT_FOUND": 404,
    "API_KEY_NOT_FOUND": 404,
    # payment required / quota
    "INSUFFICIENT_CREDITS": 402,
    "QUOTA_EXCEEDED": 429,
    "RATE_LIMITED": 429,
    # upstream / dependency
    "UPSTREAM_FAILED": 502,
    "UPSTREAM_TIMEOUT": 504,
    "PAYMENT_PROVIDER_ERROR": 502,
    "SERVICE_HANDLER_MISSING": 503,
    "PAYMENT_CONFIGURATION_ERROR": 503,
    "MAIL_DELIVERY_FAILED": 503,
    "STORAGE_ERROR": 503,
    # webhooks
    "INVALID_WEBHOOK_SIGNATURE": 400,
    "INVALID_PAYMENT_EVENT": 400,
}

_DEFAULT_STATUS = 500
_DOMAIN_ERROR_STATUS = 400


def status_for(error: DomainError) -> int:
    if error.code in _STATUS_BY_CODE:
        return _STATUS_BY_CODE[error.code]
    if isinstance(error, DomainError) and not error.__class__.__name__.startswith("Application"):
        return _DOMAIN_ERROR_STATUS
    return _DEFAULT_STATUS


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(
    *, code: str, message: str, details: dict[str, object], request_id: str | None
) -> dict[str, object]:
    return {
        "success": False,
        "code": code,
        "message": message,
        "details": details,
        "request_id": request_id,
    }


def register_exception_handlers(app: FastAPI, *, telemetry: Telemetry) -> None:
    logger = structlog.get_logger("tinysaas.errors")

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
        status = status_for(error)
        if status >= 500:
            telemetry.capture_exception(error, path=request.url.path, code=error.code)
            logger.exception("unhandled_domain_error", code=error.code)
        return JSONResponse(
            status_code=status,
            content=_envelope(
                code=error.code,
                message=error.message,
                details=error.details,
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                code="VALIDATION_ERROR",
                message="请求参数校验失败",
                details={"errors": _serializable(error.errors())},
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=_envelope(
                code=_code_for_status(error.status_code),
                message=str(error.detail),
                details={},
                request_id=_request_id(request),
            ),
            headers=getattr(error, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, error: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        telemetry.capture_exception(error, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                code="INTERNAL_ERROR",
                message="服务内部错误",
                details={},
                request_id=_request_id(request),
            ),
        )


def _code_for_status(status: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "AUTH_REQUIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }.get(status, "ERROR")


def _serializable(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
    cleaned: list[dict[str, object]] = []
    for item in errors:
        location = item.get("loc") or ()
        cleaned.append(
            {
                "loc": [str(part) for part in location],
                "msg": str(item.get("msg", "")),
                "type": str(item.get("type", "")),
            }
        )
    return cleaned
