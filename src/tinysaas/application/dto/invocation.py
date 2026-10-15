"""Invocation / usage log DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tinysaas.domain.catalog.service import ExecMode
from tinysaas.domain.invocation.invocation import Invocation, InvocationStatus


@dataclass(frozen=True, slots=True)
class InvocationView:
    """One usage log row; users only ever see their own."""

    id: UUID
    request_id: str
    user_id: UUID
    service_slug: str
    exec_mode: ExecMode
    status: InvocationStatus
    credit_cost: int
    credits_charged: int
    credits_refunded: int
    latency_ms: int | None
    upstream_status: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_invocation(cls, invocation: Invocation) -> InvocationView:
        return cls(
            id=invocation.id,
            request_id=invocation.request_id,
            user_id=invocation.user_id,
            service_slug=invocation.service_slug,
            exec_mode=invocation.exec_mode,
            status=invocation.status,
            credit_cost=invocation.credit_cost,
            credits_charged=invocation.credits_charged,
            credits_refunded=invocation.credits_refunded,
            latency_ms=invocation.latency_ms,
            upstream_status=invocation.upstream_status,
            error_code=invocation.error_code,
            error_message=invocation.error_message,
            created_at=invocation.created_at,
            finished_at=invocation.finished_at,
        )


@dataclass(frozen=True, slots=True)
class ExecutionView:
    """Synchronous ``/execute`` response."""

    invocation_id: UUID
    service_slug: str
    status_code: int
    content_type: str
    body: bytes
    latency_ms: int
    credits_charged: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class TaskView:
    """Asynchronous ``/tasks`` response."""

    task_id: UUID
    service_slug: str
    status: InvocationStatus
    credit_cost: int
    created_at: datetime
    replayed: bool = False
