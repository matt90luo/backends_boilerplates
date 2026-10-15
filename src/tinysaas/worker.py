"""arq worker: runs asynchronous service tasks.

It reuses the very same composition root as the API, so the worker and the web
process cannot drift apart. Start it with::

    uv run arq tinysaas.worker.WorkerSettings
"""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from arq import func
from arq.connections import RedisSettings
from arq.worker import Worker

from tinysaas.application.use_cases.invocations import TASK_NAME
from tinysaas.containers.container import (
    Container,
    build_container,
    start_resources,
    stop_resources,
)
from tinysaas.infrastructure.config import get_settings


async def startup(ctx: dict[str, Any]) -> None:
    container: Container = build_container()
    await start_resources(container)
    ctx["container"] = container


async def shutdown(ctx: dict[str, Any]) -> None:
    container: Container | None = ctx.get("container")
    if container is not None:
        await stop_resources(container)


async def execute_service_task(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Execute a queued invocation and settle or refund its credits."""
    container: Container = ctx["container"]
    use_case = container.run_service_task_use_case()
    body = base64.b64decode(str(payload.get("body_b64", "")))
    view = await use_case.execute(
        UUID(str(payload["invocation_id"])),
        payload=body,
        content_type=str(payload.get("content_type", "application/json")),
    )
    return view.status.value


def create_worker() -> Worker:
    settings = get_settings()
    return Worker(
        functions=[func(execute_service_task, name=TASK_NAME, timeout=300)],
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        on_startup=startup,
        on_shutdown=shutdown,
        max_jobs=10,
        job_timeout=300,
    )


class WorkerSettings:
    """arq CLI entry point (``arq tinysaas.worker.WorkerSettings``)."""

    functions = [func(execute_service_task, name=TASK_NAME, timeout=300)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 300


if __name__ == "__main__":  # pragma: no cover - manual entry point
    import asyncio

    asyncio.run(create_worker().async_run())
