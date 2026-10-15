"""IP / user based rate limiting middleware (Redis sliding window)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from tinysaas.adapters.web.client import client_ip
from tinysaas.adapters.web.lazy import Lazy
from tinysaas.application.options import RateLimitOptions
from tinysaas.application.ports.external import RateLimiter
from tinysaas.domain.access.policy import Principal

_STATUS_TOO_MANY_REQUESTS = 429


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """One protected route pattern."""

    suffix: str
    limit: int
    window_seconds: int
    scope: str = "ip"  # "ip" | "user"


class RateLimitMiddleware:
    """Applies the configured limits; fails open when the limiter errors."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: Callable[[], RateLimiter],
        options: RateLimitOptions,
        api_prefix: str,
        trusted_proxies: list[str],
    ) -> None:
        self.app = app
        self._limiter = Lazy(limiter)
        self._options = options
        self._prefix = api_prefix.rstrip("/")
        self._trusted_proxies = trusted_proxies
        self._logger = structlog.get_logger("tinysaas.ratelimit")
        self._rules = self._build_rules(options)

    @staticmethod
    def _build_rules(options: RateLimitOptions) -> list[RateLimitRule]:
        return [
            RateLimitRule("/auth/login", options.login_per_minute, 60),
            RateLimitRule("/auth/register", options.register_per_hour, 3600),
            RateLimitRule(
                "/auth/password-reset/request", options.password_reset_per_15_minutes, 900
            ),
            RateLimitRule("/services/", options.service_per_minute, 60, scope="user"),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._options.enabled:
            await self.app(scope, receive, send)
            return

        rule = self._match(scope)
        if rule is None:
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        principal: Principal | None = state.get("principal")
        if rule.scope == "user" and principal is None:
            await self.app(scope, receive, send)
            return
        identity = (
            f"user:{principal.user_id}"
            if rule.scope == "user" and principal is not None
            else f"ip:{client_ip(Request(scope, receive), trusted_proxies=self._trusted_proxies)}"
        )

        decision = await self._limiter().hit(
            key=f"{rule.suffix}:{identity}", limit=rule.limit, window_seconds=rule.window_seconds
        )
        if not decision.allowed:
            self._logger.warning(
                "rate_limited", rule=rule.suffix, identity=identity, limit=rule.limit
            )
            headers = {"Retry-After": str(decision.retry_after_seconds)}
            response = JSONResponse(
                status_code=_STATUS_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后再试",
                    "details": {
                        "limit": decision.limit,
                        "retry_after_seconds": decision.retry_after_seconds,
                    },
                    "request_id": state.get("request_id"),
                },
                headers=headers,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _match(self, scope: Scope) -> RateLimitRule | None:
        if scope.get("method") != "POST":
            return None
        path = scope.get("path", "")
        if not path.startswith(self._prefix):
            return None
        suffix = path[len(self._prefix) :]
        for rule in self._rules:
            if rule.suffix.endswith("/"):
                if suffix.startswith(rule.suffix) and suffix.endswith(("/execute", "/tasks")):
                    return rule
            elif suffix == rule.suffix:
                return rule
        return None
