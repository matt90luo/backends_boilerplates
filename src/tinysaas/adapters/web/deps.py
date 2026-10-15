"""Shared FastAPI dependencies: principal, roles, pagination, request id."""

from __future__ import annotations

from fastapi import Depends, Query, Request

from tinysaas.adapters.web.schemas.requests import Pagination
from tinysaas.application.errors import AuthenticationRequired
from tinysaas.domain.access.policy import AccessPolicy, Principal

_MAX_LIMIT = 200


async def get_request_id(request: Request) -> str:
    """Async so the dependency is resolved on the event loop.

    (A sync dependency would be executed in the anyio worker thread.)
    """
    return getattr(request.state, "request_id", "")


async def get_principal(request: Request) -> Principal:
    """Reject anonymous callers (401) — the middleware already resolved them."""
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        raise AuthenticationRequired("需要登录")
    return principal


async def get_admin(principal: Principal = Depends(get_principal)) -> Principal:
    AccessPolicy.ensure_admin(principal)
    return principal


async def get_pagination(
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)
