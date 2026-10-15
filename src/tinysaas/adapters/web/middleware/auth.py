"""Resolve credentials once per request into ``scope['state']['principal']``."""

from __future__ import annotations

from collections.abc import Callable

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from tinysaas.adapters.web.client import extract_credentials
from tinysaas.adapters.web.lazy import Lazy
from tinysaas.application.use_cases.auth import AuthenticateRequestUseCase
from tinysaas.domain.access.policy import Principal


class AuthContextMiddleware:
    """Parses ``Authorization``/``X-API-Key`` and stores the principal.

    It never rejects a request: enforcement belongs to the route dependencies
    (``require_user`` / ``require_admin``), which keeps public endpoints public.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticate: Callable[[], AuthenticateRequestUseCase],
        trusted_proxies: list[str],
    ) -> None:
        self.app = app
        self._authenticate = Lazy(authenticate)
        self._trusted_proxies = trusted_proxies
        self._logger = structlog.get_logger("tinysaas.auth")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        principal: Principal | None = None
        credentials = extract_credentials(
            Request(scope, receive), trusted_proxies=self._trusted_proxies
        )
        if credentials is not None:
            try:
                principal = await self._authenticate().execute(credentials)
            except Exception as error:  # pragma: no cover - defensive
                self._logger.warning("auth_context_failed", error=str(error))
                principal = None
        state["principal"] = principal
        if principal is not None:
            state["user_id"] = str(principal.user_id)
            structlog.contextvars.bind_contextvars(
                user_id=str(principal.user_id), role=principal.role.value
            )
        await self.app(scope, receive, send)
