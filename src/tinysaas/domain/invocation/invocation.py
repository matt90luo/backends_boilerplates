"""Invocation aggregate: one service call, with its billing outcome.

The very same aggregate is the "usage log" the dashboard reads, so the state
machine below is what the log views render.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from tinysaas.domain.catalog.service import ExecMode, Service
from tinysaas.domain.errors import ValidationError


class InvocationStatus(StrEnum):
    """Lifecycle of one call.

    ``REFUNDED`` means "the call failed and the credits were returned";
    ``FAILED`` means "the call failed and the compensation did not run", which
    needs operator attention.
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REFUNDED = "refunded"
    FAILED = "failed"


_TERMINAL_STATUSES = {
    InvocationStatus.SUCCEEDED,
    InvocationStatus.REFUNDED,
    InvocationStatus.FAILED,
}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Invocation:
    id: UUID
    request_id: str
    user_id: UUID
    service_id: UUID | None
    service_slug: str
    exec_mode: ExecMode
    credit_cost: int
    status: InvocationStatus = InvocationStatus.PENDING
    credits_charged: int = 0
    credits_refunded: int = 0
    idempotency_key: str | None = None
    latency_ms: int | None = None
    upstream_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    request_payload: str | None = None
    response_body: str | None = None
    response_content_type: str | None = None
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create_pending(
        cls,
        *,
        user_id: UUID,
        service: Service,
        request_id: str,
        idempotency_key: str | None = None,
        request_payload: str | None = None,
        now: datetime | None = None,
    ) -> Invocation:
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 255:
            raise ValidationError(
                "Idempotency-Key 长度必须在 1-255 之间", details={"field": "Idempotency-Key"}
            )
        return cls(
            id=uuid4(),
            request_id=request_id,
            user_id=user_id,
            service_id=service.id,
            service_slug=service.slug,
            exec_mode=service.exec_mode,
            credit_cost=service.credit_cost,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            created_at=now or _now(),
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def mark_queued(self, *, now: datetime | None = None) -> None:
        self._ensure_not_terminal()
        self.status = InvocationStatus.QUEUED
        self.started_at = self.started_at or (now or _now())

    def mark_running(self, *, now: datetime | None = None) -> None:
        self._ensure_not_terminal()
        self.status = InvocationStatus.RUNNING
        self.started_at = now or _now()

    def record_request(self, snapshot: str | None) -> None:
        """Store a truncated, human readable snapshot for the dashboard."""
        self.request_payload = snapshot

    def record_response(self, *, body: str | None, content_type: str | None) -> None:
        self._ensure_not_terminal()
        self.response_body = body
        self.response_content_type = content_type

    def mark_succeeded(
        self,
        *,
        latency_ms: int,
        upstream_status: int | None = None,
        now: datetime | None = None,
    ) -> None:
        self._ensure_not_terminal()
        moment = now or _now()
        self.status = InvocationStatus.SUCCEEDED
        self.credits_charged = self.credit_cost
        self.latency_ms = latency_ms
        self.upstream_status = upstream_status
        self.finished_at = moment

    def mark_failed(
        self,
        *,
        error_code: str,
        error_message: str,
        refunded: bool,
        latency_ms: int | None = None,
        upstream_status: int | None = None,
        now: datetime | None = None,
    ) -> None:
        self._ensure_not_terminal()
        moment = now or _now()
        self.status = InvocationStatus.REFUNDED if refunded else InvocationStatus.FAILED
        self.credits_charged = 0
        self.credits_refunded = self.credit_cost if refunded else 0
        self.error_code = error_code
        self.error_message = error_message
        self.latency_ms = latency_ms
        self.upstream_status = upstream_status
        self.finished_at = moment

    def _ensure_not_terminal(self) -> None:
        if self.is_terminal:
            raise ValidationError(
                "调用已结束，不能再次变更状态",
                details={"invocation_id": str(self.id), "status": self.status.value},
            )
