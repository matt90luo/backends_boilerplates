"""In-process service handlers (the built-in demo tools)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from tinysaas.application.ports.external import ExecutionResult
from tinysaas.domain.catalog.service import Service

Handler = Callable[[bytes, str], Awaitable[tuple[int, bytes, str]]]


def _elapsed_ms(started: float) -> int:
    import time

    return int((time.perf_counter() - started) * 1000)


async def echo_handler(payload: bytes, content_type: str) -> tuple[int, bytes, str]:
    """Returns the payload back, so the billing loop can be exercised."""
    try:
        parsed: Any = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = payload.decode("utf-8", errors="replace")
    body = json.dumps(
        {"service": "echo", "received": parsed, "content_type": content_type},
        ensure_ascii=False,
    ).encode("utf-8")
    return 200, body, "application/json"


async def slow_report_handler(payload: bytes, content_type: str) -> tuple[int, bytes, str]:
    """Simulates an expensive job (used to demo the async task pipeline)."""
    try:
        parsed = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        parsed = {}
    delay = float(parsed.get("delay_seconds", 2)) if isinstance(parsed, dict) else 2
    await asyncio.sleep(min(max(delay, 0.1), 10))
    body = json.dumps(
        {"service": "slow-report", "rows": 128, "status": "ready"},
        ensure_ascii=False,
    ).encode("utf-8")
    return 200, body, "application/json"


async def always_fails_handler(payload: bytes, content_type: str) -> tuple[int, bytes, str]:
    """Simulates a broken upstream so refunds can be demonstrated."""
    return 500, b'{"error":"boom"}', "application/json"


def build_demo_handlers() -> dict[str, Handler]:
    return {
        "echo": echo_handler,
        "slow-report": slow_report_handler,
        "always-fails": always_fails_handler,
    }


class InProcessServiceExecutor:
    """Adapter implementing :class:`ServiceExecutor` with local handlers."""

    def __init__(self, *, handlers: Mapping[str, Handler] | None = None) -> None:
        self._handlers: dict[str, Handler] = dict(handlers or {})

    def register(self, slug: str, handler: Handler) -> None:
        self._handlers[slug] = handler

    @property
    def slugs(self) -> list[str]:
        return sorted(self._handlers)

    async def execute(
        self,
        *,
        service: Service,
        payload: bytes,
        content_type: str,
        headers: Mapping[str, str],
    ) -> ExecutionResult:
        handler = self._handlers.get(service.slug)
        if handler is None:
            return ExecutionResult(
                ok=False,
                status_code=None,
                body=b"",
                content_type="application/json",
                latency_ms=0,
                error_code="SERVICE_HANDLER_MISSING",
                error_message=f"没有为 {service.slug} 注册本地 handler",
            )
        import time

        started = time.perf_counter()
        try:
            status, body, response_type = await asyncio.wait_for(
                handler(payload, content_type), timeout=service.timeout_secs
            )
        except TimeoutError:
            return ExecutionResult(
                ok=False,
                status_code=504,
                body=b"",
                content_type="application/json",
                latency_ms=_elapsed_ms(started),
                error_code="UPSTREAM_TIMEOUT",
                error_message="本地 handler 执行超时",
            )
        except Exception as error:  # noqa: BLE001 - surfaced as a failed call
            return ExecutionResult(
                ok=False,
                status_code=500,
                body=str(error).encode("utf-8"),
                content_type="text/plain",
                latency_ms=_elapsed_ms(started),
                error_code="UPSTREAM_FAILED",
                error_message=str(error),
            )
        return ExecutionResult(
            ok=200 <= status < 300,
            status_code=status,
            body=body,
            content_type=response_type,
            latency_ms=_elapsed_ms(started),
            error_code=None if 200 <= status < 300 else "UPSTREAM_FAILED",
            error_message=None if 200 <= status < 300 else body.decode("utf-8", "replace")[:200],
        )
