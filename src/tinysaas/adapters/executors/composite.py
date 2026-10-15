"""Chooses the right executor for a service."""

from __future__ import annotations

from collections.abc import Mapping

from tinysaas.application.ports.external import ExecutionResult, ServiceExecutor
from tinysaas.domain.catalog.service import Service


class CompositeServiceExecutor:
    """Route by configuration: ``upstream_url`` -> proxy, otherwise in-process.

    Adding a brand new tool therefore means either registering a metadata row
    with an ``upstream_url`` or (for demos/tests) registering a local handler.
    """

    def __init__(
        self,
        *,
        proxy: ServiceExecutor,
        in_process: ServiceExecutor,
        in_process_enabled: bool = True,
    ) -> None:
        self._proxy = proxy
        self._in_process = in_process
        self._in_process_enabled = in_process_enabled

    async def execute(
        self,
        *,
        service: Service,
        payload: bytes,
        content_type: str,
        headers: Mapping[str, str],
    ) -> ExecutionResult:
        if service.uses_upstream:
            return await self._proxy.execute(
                service=service, payload=payload, content_type=content_type, headers=headers
            )
        if not self._in_process_enabled:
            return ExecutionResult(
                ok=False,
                status_code=None,
                body=b"",
                content_type="application/json",
                latency_ms=0,
                error_code="SERVICE_HANDLER_MISSING",
                error_message="本地执行器已禁用，请为服务配置 upstream_url",
            )
        return await self._in_process.execute(
            service=service, payload=payload, content_type=content_type, headers=headers
        )
