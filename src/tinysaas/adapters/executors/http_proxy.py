"""HTTP reverse proxy executor for registered ``upstream_url`` services."""

from __future__ import annotations

import time
from collections.abc import Mapping

import httpx

from tinysaas.application.ports.external import ExecutionResult
from tinysaas.domain.catalog.service import Service

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "content-length",
    "host",
    "authorization",
}


class HttpProxyServiceExecutor:
    """Forwards the request body to the upstream and maps failures."""

    def __init__(self, *, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def execute(
        self,
        *,
        service: Service,
        payload: bytes,
        content_type: str,
        headers: Mapping[str, str],
    ) -> ExecutionResult:
        if not service.upstream_url:
            return ExecutionResult(
                ok=False,
                status_code=None,
                body=b"",
                content_type="application/json",
                latency_ms=0,
                error_code="SERVICE_HANDLER_MISSING",
                error_message="该服务没有配置 upstream_url",
            )
        forwarded = {
            key: value
            for key, value in headers.items()
            if key.lower() not in _HOP_BY_HOP and key.lower() != "content-type"
        }
        forwarded["Content-Type"] = content_type
        forwarded["X-Service-Slug"] = service.slug
        started = time.perf_counter()
        try:
            response = await self._client.post(
                service.upstream_url,
                content=payload,
                headers=forwarded,
                timeout=float(service.timeout_secs),
            )
        except httpx.TimeoutException:
            return ExecutionResult(
                ok=False,
                status_code=504,
                body=b"",
                content_type="application/json",
                latency_ms=_ms(started),
                error_code="UPSTREAM_TIMEOUT",
                error_message=f"上游 {service.slug} 超时",
            )
        except httpx.HTTPError as error:
            return ExecutionResult(
                ok=False,
                status_code=None,
                body=b"",
                content_type="application/json",
                latency_ms=_ms(started),
                error_code="UPSTREAM_FAILED",
                error_message=str(error),
            )

        ok = 200 <= response.status_code < 300
        return ExecutionResult(
            ok=ok,
            status_code=response.status_code,
            body=response.content,
            content_type=response.headers.get("content-type", "application/json"),
            latency_ms=_ms(started),
            error_code=None if ok else "UPSTREAM_FAILED",
            error_message=None if ok else response.text[:200],
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() not in _HOP_BY_HOP
            },
        )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
