"""Presigned upload / download endpoints (S3 compatible storage)."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from tinysaas.adapters.web.deps import get_principal, get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, ok
from tinysaas.adapters.web.schemas.payloads import (
    PresignedDownloadPayload,
    PresignedUploadPayload,
)
from tinysaas.adapters.web.schemas.requests import (
    PresignDownloadRequest,
    PresignUploadRequest,
)
from tinysaas.application.dto.commands import PresignDownloadQuery, PresignUploadCommand
from tinysaas.application.use_cases.files import (
    PresignDownloadUseCase,
    PresignUploadUseCase,
)
from tinysaas.containers.container import Container
from tinysaas.domain.access.policy import Principal

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/presign", response_model=Envelope[PresignedUploadPayload])
@inject
async def presign_upload(
    payload: PresignUploadRequest,
    use_case: PresignUploadUseCase = Depends(Provide[Container.presign_upload_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[PresignedUploadPayload]:
    """Client uploads straight to storage; bytes never touch this service."""
    view = await use_case.execute(
        principal,
        PresignUploadCommand(
            purpose=payload.purpose,
            content_type=payload.content_type,
            size=payload.size,
            filename=payload.filename,
        ),
    )
    return ok(PresignedUploadPayload.model_validate(view), request_id=request_id)


@router.post("/presign/download", response_model=Envelope[PresignedDownloadPayload])
@inject
async def presign_download(
    payload: PresignDownloadRequest,
    use_case: PresignDownloadUseCase = Depends(Provide[Container.presign_download_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[PresignedDownloadPayload]:
    """Only the owner (or an admin) can mint a download URL for a key."""
    view = await use_case.execute(
        principal,
        PresignDownloadQuery(key=payload.key, download_name=payload.download_name),
    )
    return ok(PresignedDownloadPayload.model_validate(view), request_id=request_id)
