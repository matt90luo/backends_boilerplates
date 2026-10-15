"""Administrator endpoints: service CRUD, user management and global logs."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, status

from tinysaas.adapters.web.deps import get_admin, get_pagination, get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, PagePayload, ok
from tinysaas.adapters.web.schemas.payloads import (
    AdminUserPayload,
    InvocationPayload,
    LedgerEntryPayload,
    ServicePayload,
)
from tinysaas.adapters.web.schemas.requests import (
    CreateServiceRequest,
    GrantCreditsRequest,
    Pagination,
    UpdateServiceRequest,
    UpdateUserRequest,
)
from tinysaas.application.dto.commands import (
    CreateServiceCommand,
    GrantCreditsCommand,
    ListServicesQuery,
    ListUserInvocationsQuery,
    ListUsersQuery,
    UpdateServiceCommand,
    UpdateUserCommand,
)
from tinysaas.application.use_cases.admin_users import (
    GetUserUseCase,
    ListUsersUseCase,
    UpdateUserUseCase,
)
from tinysaas.application.use_cases.billing import GrantCreditsUseCase
from tinysaas.application.use_cases.catalog import (
    CreateServiceUseCase,
    DeactivateServiceUseCase,
    ListServicesUseCase,
    UpdateServiceUseCase,
)
from tinysaas.application.use_cases.invocations import ListAllInvocationsUseCase
from tinysaas.containers.container import Container
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.invocation.invocation import InvocationStatus

router = APIRouter(prefix="/admin", tags=["admin"])


# --- services --------------------------------------------------------------
@router.post("/services", response_model=Envelope[ServicePayload], status_code=201)
@inject
async def create_service(
    payload: CreateServiceRequest,
    use_case: CreateServiceUseCase = Depends(Provide[Container.create_service_use_case]),
    principal: Principal = Depends(get_admin),
    request_id: str = Depends(get_request_id),
) -> Envelope[ServicePayload]:
    """Register a new tool: no gateway restart, no new route code."""
    service = await use_case.execute(
        principal,
        CreateServiceCommand(
            slug=payload.slug,
            name=payload.name,
            credit_cost=payload.credit_cost,
            exec_mode=payload.exec_mode,
            description=payload.description,
            upstream_url=payload.upstream_url,
            timeout_secs=payload.timeout_secs,
            is_active=payload.is_active,
        ),
    )
    return ok(ServicePayload.model_validate(service), request_id=request_id)


@router.patch("/services/{service_id}", response_model=Envelope[ServicePayload])
@inject
async def update_service(
    service_id: UUID,
    payload: UpdateServiceRequest,
    use_case: UpdateServiceUseCase = Depends(Provide[Container.update_service_use_case]),
    principal: Principal = Depends(get_admin),
    request_id: str = Depends(get_request_id),
) -> Envelope[ServicePayload]:
    service = await use_case.execute(
        principal,
        service_id,
        UpdateServiceCommand(
            name=payload.name,
            description=payload.description,
            credit_cost=payload.credit_cost,
            exec_mode=payload.exec_mode,
            upstream_url=payload.upstream_url,
            clear_upstream_url=payload.clear_upstream_url,
            timeout_secs=payload.timeout_secs,
            is_active=payload.is_active,
        ),
    )
    return ok(ServicePayload.model_validate(service), request_id=request_id)


@router.delete("/services/{service_id}", response_model=Envelope[ServicePayload])
@inject
async def deactivate_service(
    service_id: UUID,
    use_case: DeactivateServiceUseCase = Depends(Provide[Container.deactivate_service_use_case]),
    principal: Principal = Depends(get_admin),
    request_id: str = Depends(get_request_id),
) -> Envelope[ServicePayload]:
    """Soft delete so historical usage logs stay readable."""
    service = await use_case.execute(principal, service_id)
    return ok(ServicePayload.model_validate(service), request_id=request_id)


@router.get("/services", response_model=Envelope[PagePayload[ServicePayload]])
@inject
async def list_services(
    use_case: ListServicesUseCase = Depends(Provide[Container.list_services_use_case]),
    principal: Principal = Depends(get_admin),
    pagination: Pagination = Depends(get_pagination),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[ServicePayload]]:
    page = await use_case.execute(
        principal,
        ListServicesQuery(include_inactive=True, limit=pagination.limit, offset=pagination.offset),
    )
    payload = PagePayload[ServicePayload](
        items=[ServicePayload.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)


# --- users -----------------------------------------------------------------
@router.get("/users", response_model=Envelope[PagePayload[AdminUserPayload]])
@inject
async def list_users(
    use_case: ListUsersUseCase = Depends(Provide[Container.list_users_use_case]),
    principal: Principal = Depends(get_admin),
    pagination: Pagination = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=320),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[AdminUserPayload]]:
    page = await use_case.execute(
        principal,
        ListUsersQuery(search=search, limit=pagination.limit, offset=pagination.offset),
    )
    payload = PagePayload[AdminUserPayload](
        items=[AdminUserPayload.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)


@router.get("/users/{user_id}", response_model=Envelope[AdminUserPayload])
@inject
async def get_user(
    user_id: UUID,
    use_case: GetUserUseCase = Depends(Provide[Container.get_user_use_case]),
    principal: Principal = Depends(get_admin),
    request_id: str = Depends(get_request_id),
) -> Envelope[AdminUserPayload]:
    user = await use_case.execute(principal, user_id)
    return ok(AdminUserPayload.model_validate(user), request_id=request_id)


@router.patch("/users/{user_id}", response_model=Envelope[AdminUserPayload])
@inject
async def update_user(
    user_id: UUID,
    payload: UpdateUserRequest,
    use_case: UpdateUserUseCase = Depends(Provide[Container.update_user_use_case]),
    principal: Principal = Depends(get_admin),
    request_id: str = Depends(get_request_id),
) -> Envelope[AdminUserPayload]:
    """Change role / plan / quota / activation; admins cannot demote themselves."""
    user = await use_case.execute(
        principal,
        user_id,
        UpdateUserCommand(
            role=payload.role,
            plan=payload.plan,
            daily_quota=payload.daily_quota,
            is_active=payload.is_active,
        ),
    )
    return ok(AdminUserPayload.model_validate(user), request_id=request_id)


@router.post(
    "/users/{user_id}/credits",
    response_model=Envelope[LedgerEntryPayload],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def grant_credits(
    user_id: UUID,
    payload: GrantCreditsRequest,
    use_case: GrantCreditsUseCase = Depends(Provide[Container.grant_credits_use_case]),
    principal: Principal = Depends(get_admin),
    request_id: str = Depends(get_request_id),
) -> Envelope[LedgerEntryPayload]:
    """Manual credit adjustment; always writes an ``admin_adjust`` ledger row."""
    entry = await use_case.execute(
        principal,
        GrantCreditsCommand(user_id=user_id, amount=payload.amount, reason=payload.reason),
    )
    return ok(LedgerEntryPayload.model_validate(entry), request_id=request_id)


# --- logs ------------------------------------------------------------------
@router.get("/invocations", response_model=Envelope[PagePayload[InvocationPayload]])
@inject
async def list_all_invocations(
    use_case: ListAllInvocationsUseCase = Depends(Provide[Container.list_all_invocations_use_case]),
    principal: Principal = Depends(get_admin),
    pagination: Pagination = Depends(get_pagination),
    user_id: UUID | None = Query(default=None),
    status_filter: InvocationStatus | None = Query(default=None, alias="status"),
    service_slug: str | None = Query(default=None),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[InvocationPayload]]:
    """Every usage log row, filterable by user / service / status."""
    page = await use_case.execute(
        principal,
        ListUserInvocationsQuery(
            user_id=user_id,
            status=status_filter,
            service_slug=service_slug,
            limit=pagination.limit,
            offset=pagination.offset,
        ),
    )
    payload = PagePayload[InvocationPayload](
        items=[InvocationPayload.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)


@router.get("/users/{user_id}/invocations", response_model=Envelope[PagePayload[InvocationPayload]])
@inject
async def list_user_invocations(
    user_id: UUID,
    use_case: ListAllInvocationsUseCase = Depends(Provide[Container.list_all_invocations_use_case]),
    principal: Principal = Depends(get_admin),
    pagination: Pagination = Depends(get_pagination),
    status_filter: InvocationStatus | None = Query(default=None, alias="status"),
    service_slug: str | None = Query(default=None),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[InvocationPayload]]:
    """Inspect one user's usage logs."""
    page = await use_case.execute(
        principal,
        ListUserInvocationsQuery(
            user_id=user_id,
            status=status_filter,
            service_slug=service_slug,
            limit=pagination.limit,
            offset=pagination.offset,
        ),
    )
    payload = PagePayload[InvocationPayload](
        items=[InvocationPayload.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)
