"""Request helpers shared by the middleware and the route dependencies."""

from __future__ import annotations

from starlette.requests import Request

from tinysaas.application.dto.commands import Credentials

API_KEY_HEADER = "X-API-Key"


def client_ip(request: Request, *, trusted_proxies: list[str]) -> str:
    """Resolve the client address, honouring X-Forwarded-For only when trusted."""
    peer = request.client.host if request.client else "unknown"
    if not trusted_proxies or peer not in trusted_proxies:
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "")
    if not forwarded:
        return peer
    return forwarded.split(",")[0].strip() or peer


def extract_credentials(request: Request, *, trusted_proxies: list[str]) -> Credentials | None:
    """Pull a bearer token or API key out of the headers."""
    ip_address = client_ip(request, trusted_proxies=trusted_proxies)
    user_agent = request.headers.get("User-Agent")
    api_key = request.headers.get(API_KEY_HEADER)
    if api_key:
        return Credentials(
            scheme="api_key", value=api_key, user_agent=user_agent, ip_address=ip_address
        )
    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return Credentials(
            scheme="bearer",
            value=value.strip(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
    return None
