"""The gateway core: dispatch a service call and charge for it.

Flow (two phase, compensating transaction):

1. reserve credits in a short transaction and write a ``pending`` invocation;
2. dispatch to the executor with **no** transaction held;
3. settle on 2xx, refund on anything else, and always leave a log row.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import UUID

from tinysaas.application.dto.commands import (
    ExecuteServiceCommand,
    ListInvocationsQuery,
    ListUserInvocationsQuery,
    SubmitServiceTaskCommand,
)
from tinysaas.application.dto.common import Page
from tinysaas.application.dto.invocation import ExecutionView, InvocationView, TaskView
from tinysaas.application.errors import (
    ApplicationError,
    ExecModeMismatch,
    IdempotencyConflict,
    InvocationNotFound,
    QuotaExceeded,
    ServiceHandlerMissing,
    ServiceNotFound,
    UpstreamFailed,
    UpstreamTimeout,
    UserNotFound,
    error_from_code,
)
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.external import ExecutionResult, ServiceExecutor, TaskQueue
from tinysaas.application.ports.observability import AppLogger
from tinysaas.application.ports.persistence import UnitOfWork, UnitOfWorkFactory
from tinysaas.domain.access.policy import AccessPolicy, Principal
from tinysaas.domain.billing.service import CreditReservationService
from tinysaas.domain.catalog.service import ExecMode, Service
from tinysaas.domain.errors import ValidationError
from tinysaas.domain.invocation.invocation import Invocation, InvocationStatus

TASK_NAME = "tinysaas.execute_service_task"
MAX_TASK_PAYLOAD_BYTES = 512 * 1024
_LOG_BODY_LIMIT = 64 * 1024
_REQUEST_SNAPSHOT_LIMIT = 2_000


def start_of_day(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def snapshot_text(body: bytes, *, limit: int) -> str | None:
    """Best effort, bounded textual snapshot for the log row."""
    if not body:
        return None
    return body.decode("utf-8", errors="replace")[:limit]


class InvocationSettlement:
    """Phase 3 collaborator shared by the sync route and the worker."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        credits: CreditReservationService,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._credits = credits
        self._clock = clock
        self._logger = logger

    async def finish(self, *, invocation_id: UUID, result: ExecutionResult) -> Invocation:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            invocation = await uow.invocations.get(invocation_id)
            if invocation is None:
                raise InvocationNotFound("调用记录不存在")
            wallet = await uow.wallets.get_for_update(invocation.user_id)
            if wallet is None:
                raise UserNotFound("用户钱包不存在")
            invocation.record_response(
                body=snapshot_text(result.body, limit=_LOG_BODY_LIMIT),
                content_type=result.content_type,
            )
            if result.ok:
                entry = self._credits.settle(
                    wallet=wallet,
                    invocation=invocation,
                    latency_ms=result.latency_ms,
                    upstream_status=result.status_code,
                    now=now,
                )
            else:
                entry = self._credits.refund(
                    wallet=wallet,
                    invocation=invocation,
                    error_code=result.error_code or "UPSTREAM_FAILED",
                    error_message=result.error_message or "上游服务调用失败",
                    latency_ms=result.latency_ms,
                    upstream_status=result.status_code,
                    now=now,
                )
            await uow.invocations.update(invocation)
            await uow.wallets.update(wallet)
            await uow.ledger.add(entry)
            await uow.commit()
        self._logger.info(
            "invocation_finished",
            invocation_id=str(invocation.id),
            user_id=str(invocation.user_id),
            service_slug=invocation.service_slug,
            status=invocation.status.value,
            latency_ms=invocation.latency_ms,
        )
        return invocation


def failure_error(result: ExecutionResult, invocation: Invocation) -> ApplicationError:
    details: dict[str, object] = {
        "invocation_id": str(invocation.id),
        "upstream_status": result.status_code,
        "upstream_error": result.error_code,
    }
    if result.error_code == UpstreamTimeout.code or result.status_code == 504:
        return UpstreamTimeout("上游服务超时，credit 已退回", details=details)
    return UpstreamFailed("上游服务调用失败，credit 已退回", details=details)


class ExecuteServiceUseCase:
    """Synchronous virtual dispatcher: ``POST /services/{slug}/execute``."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        credits: CreditReservationService,
        executor: ServiceExecutor,
        settlement: InvocationSettlement,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._credits = credits
        self._executor = executor
        self._settlement = settlement
        self._clock = clock
        self._logger = logger

    async def execute(self, command: ExecuteServiceCommand) -> ExecutionView:
        principal = command.principal
        now = self._clock.now()
        async with self._uow_factory() as uow:
            service = await self._load_service(uow, command.service_slug)
            AccessPolicy.ensure_can_invoke(principal, service)
            if service.exec_mode is not ExecMode.SYNC:
                raise ExecModeMismatch(
                    "该服务是异步服务，请调用 POST /services/{slug}/tasks",
                    details={"service_slug": service.slug, "exec_mode": service.exec_mode.value},
                )
            if command.idempotency_key:
                existing = await uow.invocations.get_by_idempotency_key(
                    principal.user_id, command.idempotency_key
                )
                if existing is not None:
                    if not existing.is_terminal:
                        raise IdempotencyConflict(
                            "相同 Idempotency-Key 的调用仍在进行中",
                            details={"invocation_id": str(existing.id)},
                        )
                    return self._replay(existing)
            await self._check_quota(uow, principal, now=now)
            wallet = await uow.wallets.get_for_update(principal.user_id)
            if wallet is None:
                raise UserNotFound("用户钱包不存在")
            invocation = Invocation.create_pending(
                user_id=principal.user_id,
                service=service,
                request_id=command.request_id,
                idempotency_key=command.idempotency_key,
                request_payload=snapshot_text(command.payload, limit=_REQUEST_SNAPSHOT_LIMIT),
                now=now,
            )
            entry = self._credits.reserve(wallet=wallet, invocation=invocation, now=now)
            invocation.mark_running(now=now)
            await uow.invocations.add(invocation)
            await uow.wallets.update(wallet)
            await uow.ledger.add(entry)
            await uow.commit()

        result = await self._executor.execute(
            service=service,
            payload=command.payload,
            content_type=command.content_type,
            headers=command.headers,
        )
        finished = await self._settlement.finish(invocation_id=invocation.id, result=result)
        if not result.ok:
            raise failure_error(result, finished)
        return ExecutionView(
            invocation_id=finished.id,
            service_slug=finished.service_slug,
            status_code=result.status_code or 200,
            content_type=result.content_type,
            body=result.body,
            latency_ms=result.latency_ms,
            credits_charged=finished.credits_charged,
        )

    async def _load_service(self, uow: UnitOfWork, slug: str) -> Service:
        service = await uow.services.get_by_slug(slug)
        if service is None:
            raise ServiceNotFound("服务不存在", details={"service_slug": slug})
        return service

    async def _check_quota(self, uow: UnitOfWork, principal: Principal, *, now: datetime) -> None:
        used = await uow.invocations.count_since(principal.user_id, start_of_day(now))
        if used >= principal.daily_quota:
            raise QuotaExceeded(
                "今日调用额度已用完",
                details={"used": used, "limit": principal.daily_quota},
            )

    @staticmethod
    def _replay(existing: Invocation) -> ExecutionView:
        if existing.status is InvocationStatus.SUCCEEDED:
            return ExecutionView(
                invocation_id=existing.id,
                service_slug=existing.service_slug,
                status_code=existing.upstream_status or 200,
                content_type=existing.response_content_type or "application/json",
                body=(existing.response_body or "").encode(),
                latency_ms=existing.latency_ms or 0,
                credits_charged=existing.credits_charged,
                replayed=True,
            )
        raise error_from_code(
            existing.error_code or UpstreamFailed.code,
            existing.error_message or "上游服务调用失败",
            details={"invocation_id": str(existing.id), "replayed": True},
        )


class SubmitServiceTaskUseCase:
    """Asynchronous dispatcher: reserve now, execute in the worker."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        credits: CreditReservationService,
        queue: TaskQueue,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._credits = credits
        self._queue = queue
        self._clock = clock
        self._logger = logger

    async def execute(self, command: SubmitServiceTaskCommand) -> TaskView:
        principal = command.principal
        now = self._clock.now()
        if len(command.payload) > MAX_TASK_PAYLOAD_BYTES:
            raise ValidationError(
                f"任务请求体不能超过 {MAX_TASK_PAYLOAD_BYTES} 字节",
                details={"field": "payload"},
            )
        async with self._uow_factory() as uow:
            service = await uow.services.get_by_slug(command.service_slug)
            if service is None:
                raise ServiceNotFound("服务不存在", details={"service_slug": command.service_slug})
            AccessPolicy.ensure_can_invoke(principal, service)
            if service.exec_mode is not ExecMode.ASYNC:
                raise ExecModeMismatch(
                    "该服务是同步服务，请调用 POST /services/{slug}/execute",
                    details={"service_slug": service.slug, "exec_mode": service.exec_mode.value},
                )
            if command.idempotency_key:
                existing = await uow.invocations.get_by_idempotency_key(
                    principal.user_id, command.idempotency_key
                )
                if existing is not None:
                    return TaskView(
                        task_id=existing.id,
                        service_slug=existing.service_slug,
                        status=existing.status,
                        credit_cost=existing.credit_cost,
                        created_at=existing.created_at,
                        replayed=True,
                    )
            used = await uow.invocations.count_since(principal.user_id, start_of_day(now))
            if used >= principal.daily_quota:
                raise QuotaExceeded(
                    "今日调用额度已用完",
                    details={"used": used, "limit": principal.daily_quota},
                )
            wallet = await uow.wallets.get_for_update(principal.user_id)
            if wallet is None:
                raise UserNotFound("用户钱包不存在")
            invocation = Invocation.create_pending(
                user_id=principal.user_id,
                service=service,
                request_id=command.request_id,
                idempotency_key=command.idempotency_key,
                request_payload=snapshot_text(command.payload, limit=_REQUEST_SNAPSHOT_LIMIT),
                now=now,
            )
            entry = self._credits.reserve(wallet=wallet, invocation=invocation, now=now)
            invocation.mark_queued(now=now)
            await uow.invocations.add(invocation)
            await uow.wallets.update(wallet)
            await uow.ledger.add(entry)
            await uow.commit()

        job_id = await self._enqueue(
            invocation,
            service=service,
            content_type=command.content_type,
            payload=command.payload,
        )
        if job_id is None:
            raise ServiceHandlerMissing(
                "任务队列不可用，credit 已退回",
                details={"invocation_id": str(invocation.id)},
            )
        self._logger.info(
            "service_task_queued",
            invocation_id=str(invocation.id),
            user_id=str(principal.user_id),
            service_slug=service.slug,
        )
        return TaskView(
            task_id=invocation.id,
            service_slug=invocation.service_slug,
            status=invocation.status,
            credit_cost=invocation.credit_cost,
            created_at=invocation.created_at,
        )

    async def _enqueue(
        self,
        invocation: Invocation,
        *,
        service: Service,
        content_type: str,
        payload: bytes,
    ) -> str | None:
        job_payload: dict[str, object] = {
            "invocation_id": str(invocation.id),
            "service_slug": service.slug,
            "content_type": content_type,
            "body_b64": base64.b64encode(payload).decode("ascii"),
        }
        try:
            return await self._queue.enqueue(
                TASK_NAME, job_payload, job_id=f"invocation:{invocation.id}"
            )
        except Exception as error:
            self._logger.exception(
                "service_task_enqueue_failed",
                invocation_id=str(invocation.id),
                error=str(error),
            )
            await self._compensate(invocation)
            return None

    async def _compensate(self, invocation: Invocation) -> None:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            fresh = await uow.invocations.get(invocation.id)
            if fresh is None or fresh.is_terminal:
                return
            wallet = await uow.wallets.get_for_update(fresh.user_id)
            if wallet is None:
                return
            entry = self._credits.refund(
                wallet=wallet,
                invocation=fresh,
                error_code="TASK_ENQUEUE_FAILED",
                error_message="任务入队失败",
                now=now,
            )
            await uow.invocations.update(fresh)
            await uow.wallets.update(wallet)
            await uow.ledger.add(entry)
            await uow.commit()


class RunServiceTaskUseCase:
    """Worker entry point: execute a queued invocation and settle it."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        credits: CreditReservationService,
        executor: ServiceExecutor,
        settlement: InvocationSettlement,
        clock: Clock,
        logger: AppLogger,
    ) -> None:
        self._uow_factory = uow_factory
        self._credits = credits
        self._executor = executor
        self._settlement = settlement
        self._clock = clock
        self._logger = logger

    async def execute(
        self, invocation_id: UUID, *, payload: bytes, content_type: str
    ) -> InvocationView:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            invocation = await uow.invocations.get(invocation_id)
            if invocation is None:
                raise InvocationNotFound("调用记录不存在")
            if invocation.is_terminal:
                return InvocationView.from_invocation(invocation)
            service = None
            if invocation.service_id is not None:
                service = await uow.services.get(invocation.service_id)
            if service is None:
                service = await uow.services.get_by_slug(invocation.service_slug)
            if service is None:
                wallet = await uow.wallets.get_for_update(invocation.user_id)
                if wallet is not None:
                    entry = self._credits.refund(
                        wallet=wallet,
                        invocation=invocation,
                        error_code=ServiceNotFound.code,
                        error_message="服务已被删除",
                        now=now,
                    )
                    await uow.ledger.add(entry)
                    await uow.wallets.update(wallet)
                await uow.invocations.update(invocation)
                await uow.commit()
                return InvocationView.from_invocation(invocation)
            invocation.mark_running(now=now)
            await uow.invocations.update(invocation)
            await uow.commit()

        result = await self._executor.execute(
            service=service, payload=payload, content_type=content_type, headers={}
        )
        finished = await self._settlement.finish(invocation_id=invocation.id, result=result)
        return InvocationView.from_invocation(finished)


class GetTaskUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, task_id: UUID) -> InvocationView:
        async with self._uow_factory() as uow:
            invocation = await uow.invocations.get(task_id)
        if invocation is None:
            raise InvocationNotFound("任务不存在")
        AccessPolicy.ensure_can_view_invocation(principal, invocation.user_id)
        return InvocationView.from_invocation(invocation)


class ListMyInvocationsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, principal: Principal, query: ListInvocationsQuery
    ) -> Page[InvocationView]:
        async with self._uow_factory() as uow:
            rows, total = await uow.invocations.list_for_user(
                principal.user_id,
                limit=query.limit,
                offset=query.offset,
                status=query.status,
                service_slug=query.service_slug,
            )
        return self._page(rows, total, query)

    @staticmethod
    def _page(
        rows: list[Invocation], total: int, query: ListInvocationsQuery
    ) -> Page[InvocationView]:
        return Page(
            items=[InvocationView.from_invocation(row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )


class GetInvocationUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, invocation_id: UUID) -> InvocationView:
        async with self._uow_factory() as uow:
            invocation = await uow.invocations.get(invocation_id)
        if invocation is None:
            raise InvocationNotFound("调用日志不存在")
        AccessPolicy.ensure_can_view_invocation(principal, invocation.user_id)
        return InvocationView.from_invocation(invocation)


class ListAllInvocationsUseCase:
    """Admin view: every log row, optionally filtered by user."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, principal: Principal, query: ListUserInvocationsQuery
    ) -> Page[InvocationView]:
        AccessPolicy.ensure_admin(principal)
        async with self._uow_factory() as uow:
            rows, total = await uow.invocations.list_all(
                limit=query.limit,
                offset=query.offset,
                user_id=query.user_id,
                status=query.status,
                service_slug=query.service_slug,
            )
        return Page(
            items=[InvocationView.from_invocation(row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
