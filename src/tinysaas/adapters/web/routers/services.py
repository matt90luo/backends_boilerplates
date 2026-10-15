"""Service catalogue, the virtual dispatcher and task polling."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from tinysaas.adapters.web.deps import get_pagination, get_principal, get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, PagePayload, ok
from tinysaas.adapters.web.schemas.payloads import InvocationPayload, ServicePayload, TaskPayload
from tinysaas.adapters.web.schemas.requests import Pagination
from tinysaas.application.dto.commands import (
    ExecuteServiceCommand,
    ListInvocationsQuery,
    ListServicesQuery,
    SubmitServiceTaskCommand,
)
from tinysaas.application.use_cases.catalog import GetServiceUseCase, ListServicesUseCase
from tinysaas.application.use_cases.invocations import (
    ExecuteServiceUseCase,
    GetInvocationUseCase,
    GetTaskUseCase,
    ListMyInvocationsUseCase,
    SubmitServiceTaskUseCase,
)
from tinysaas.containers.container import Container
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.invocation.invocation import InvocationStatus

router = APIRouter(tags=["services"])


@router.get("/services", response_model=Envelope[PagePayload[ServicePayload]])
@inject
async def list_services(
    use_case: ListServicesUseCase = Depends(Provide[Container.list_services_use_case]),
    principal: Principal = Depends(get_principal),
    pagination: Pagination = Depends(get_pagination),
    include_inactive: bool = Query(default=False),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[ServicePayload]]:
    """Public catalogue; ``include_inactive`` is honoured for admins only."""
    page = await use_case.execute(
        principal,
        ListServicesQuery(
            include_inactive=include_inactive, limit=pagination.limit, offset=pagination.offset
        ),
    )
    payload = PagePayload[ServicePayload](
        items=[ServicePayload.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)


@router.get("/services/{slug}", response_model=Envelope[ServicePayload])
@inject
async def get_service(
    slug: str,
    use_case: GetServiceUseCase = Depends(Provide[Container.get_service_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[ServicePayload]:
    service = await use_case.execute(principal, slug)
    return ok(ServicePayload.model_validate(service), request_id=request_id)


@router.post(
    "/services/{slug}/execute",
    status_code=status.HTTP_200_OK,
    response_class=Response,
    responses={
        200: {"description": "上游服务的原始响应体（可能是二进制）"},
        402: {"description": "credit 不足"},
        502: {"description": "上游失败，credit 已退回"},
    },
)
@inject
async def execute_service(
    slug: str,
    request: Request,
    use_case: ExecuteServiceUseCase = Depends(Provide[Container.execute_service_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
) -> Response:
    """Synchronous virtual dispatcher.

    Unlike the rest of the API this endpoint streams the *upstream* body back
    (a tool may return an image), so it is not wrapped in the JSON envelope.
    Billing metadata travels in ``X-Invocation-Id`` / ``X-Credits-Charged``.
    """
    result = await use_case.execute(
        ExecuteServiceCommand(
            principal=principal,
            service_slug=slug,
            payload=await request.body(),
            content_type=request.headers.get("content-type", "application/json"),
            headers=dict(request.headers),
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
    )
    return Response(
        content=result.body,
        media_type=result.content_type,
        status_code=result.status_code,
        headers={
            "X-Invocation-Id": str(result.invocation_id),
            "X-Credits-Charged": str(result.credits_charged),
            "X-Latency-Ms": str(result.latency_ms),
            "X-Replayed": "true" if result.replayed else "false",
        },
    )


@router.post(
    "/services/{slug}/tasks",
    response_model=Envelope[TaskPayload],
    status_code=status.HTTP_202_ACCEPTED,
)
@inject
async def submit_task(
    slug: str,
    request: Request,
    use_case: SubmitServiceTaskUseCase = Depends(Provide[Container.submit_service_task_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
) -> Envelope[TaskPayload]:
    """Submit a long running call: credits are reserved, then settled by the worker."""
    task = await use_case.execute(
        SubmitServiceTaskCommand(
            principal=principal,
            service_slug=slug,
            payload=await request.body(),
            content_type=request.headers.get("content-type", "application/json"),
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
    )
    return ok(TaskPayload.model_validate(task), request_id=request_id)


@router.get("/tasks/{task_id}", response_model=Envelope[InvocationPayload])
@inject
async def get_task(
    task_id: UUID,
    use_case: GetTaskUseCase = Depends(Provide[Container.get_task_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[InvocationPayload]:
    invocation = await use_case.execute(principal, task_id)
    return ok(InvocationPayload.model_validate(invocation), request_id=request_id)


@router.get("/me/invocations", response_model=Envelope[PagePayload[InvocationPayload]])
@inject
async def list_my_invocations(
    use_case: ListMyInvocationsUseCase = Depends(Provide[Container.list_my_invocations_use_case]),
    principal: Principal = Depends(get_principal),
    pagination: Pagination = Depends(get_pagination),
    status_filter: InvocationStatus | None = Query(default=None, alias="status"),
    service_slug: str | None = Query(default=None),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[InvocationPayload]]:
    """A user only ever sees their own usage logs."""
    page = await use_case.execute(
        principal,
        ListInvocationsQuery(
            limit=pagination.limit,
            offset=pagination.offset,
            status=status_filter,
            service_slug=service_slug,
        ),
    )
    payload = PagePayload[InvocationPayload](
        items=[InvocationPayload.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)


@router.get("/me/invocations/{invocation_id}", response_model=Envelope[InvocationPayload])
@inject
async def get_my_invocation(
    invocation_id: UUID,
    use_case: GetInvocationUseCase = Depends(Provide[Container.get_invocation_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[InvocationPayload]:
    invocation = await use_case.execute(principal, invocation_id)
    return ok(InvocationPayload.model_validate(invocation), request_id=request_id)
