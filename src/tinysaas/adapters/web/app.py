"""FastAPI application factory.

The app only *assembles* middleware and routers; every dependency comes from
the composition root (``containers.container``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tinysaas.adapters.web.errors import register_exception_handlers
from tinysaas.adapters.web.middleware.auth import AuthContextMiddleware
from tinysaas.adapters.web.middleware.context import RequestContextMiddleware
from tinysaas.adapters.web.middleware.ratelimit import RateLimitMiddleware
from tinysaas.adapters.web.routers import (
    admin,
    auth,
    billing,
    files,
    health,
    services,
    users,
    webhooks,
)
from tinysaas.containers.container import (
    Container,
    build_container,
    start_resources,
    stop_resources,
)

DESCRIPTION = """
Tiny SaaS backend boilerplate (DDD + composition root).

* **auth** – JWT access tokens, rotating refresh tokens stored server side, API keys
* **billing** – credit wallet with reserve / settle / refund and a Stripe Checkout top-up
* **services** – a virtual dispatcher: `POST /services/{slug}/execute` (sync) and
  `POST /services/{slug}/tasks` (async worker)
* **logs** – every call is an `invocation` row; users see their own, admins see all

All endpoints answer with `{"success": true, "data": ...}` and errors with
`{"success": false, "code": ..., "message": ..., "details": ..., "request_id": ...}`.
The only exceptions are the raw tool response of `execute` and the provider webhook.
"""


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()
    settings = container.settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await start_resources(container)
        try:
            yield
        finally:
            await stop_resources(container)

    app = FastAPI(
        title="tiny SaaS backend",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.container = container

    register_exception_handlers(app, telemetry=container.telemetry())

    # Middleware is applied bottom-up: the last one added is the outermost.
    app.add_middleware(
        RateLimitMiddleware,
        limiter=container.rate_limiter,
        options=container.options().rate_limit,
        api_prefix=settings.api_prefix,
        trusted_proxies=settings.proxy_hosts,
    )
    app.add_middleware(
        AuthContextMiddleware,
        authenticate=container.authenticate_request_use_case,
        trusted_proxies=settings.proxy_hosts,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Invocation-Id", "X-Credits-Charged"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    for module in (auth, users, billing, services, admin, files, webhooks):
        app.include_router(module.router, prefix=settings.api_prefix)

    return app
