"""Liveness and readiness probes."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Response, status

from tinysaas.adapters.web.deps import get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, ok
from tinysaas.adapters.web.schemas.payloads import HealthPayload
from tinysaas.application.use_cases.readiness import CheckReadinessUseCase
from tinysaas.containers.container import Container

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=Envelope[HealthPayload])
async def healthz(request_id: str = Depends(get_request_id)) -> Envelope[HealthPayload]:
    """Liveness: the process is up (do not probe dependencies here)."""
    return ok(HealthPayload(status="ok", components={}), request_id=request_id)


@router.get("/readyz", response_model=Envelope[HealthPayload])
@inject
async def readyz(
    response: Response,
    use_case: CheckReadinessUseCase = Depends(Provide[Container.check_readiness_use_case]),
    request_id: str = Depends(get_request_id),
) -> Envelope[HealthPayload]:
    """Readiness: PostgreSQL, Redis and object storage must all answer."""
    report = await use_case.execute()
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ok(
        HealthPayload(status=report.status, components=report.components),
        request_id=request_id,
    )
