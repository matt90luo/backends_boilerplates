"""Current user profile and API key endpoints."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Response, status

from tinysaas.adapters.web.deps import get_principal, get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, PagePayload, ok
from tinysaas.adapters.web.schemas.payloads import (
    ApiKeyIssuedPayload,
    ApiKeyPayload,
    UserPayload,
)
from tinysaas.adapters.web.schemas.requests import (
    ChangePasswordRequest,
    CreateApiKeyRequest,
    UpdateProfileRequest,
)
from tinysaas.application.dto.commands import (
    ChangePasswordCommand,
    CreateApiKeyCommand,
    UpdateProfileCommand,
)
from tinysaas.application.use_cases.api_keys import (
    CreateApiKeyUseCase,
    ListApiKeysUseCase,
    RevokeApiKeyUseCase,
)
from tinysaas.application.use_cases.profile import (
    ChangePasswordUseCase,
    GetProfileUseCase,
    UpdateProfileUseCase,
)
from tinysaas.containers.container import Container
from tinysaas.domain.access.policy import Principal

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=Envelope[UserPayload])
@inject
async def get_me(
    use_case: GetProfileUseCase = Depends(Provide[Container.get_profile_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[UserPayload]:
    user = await use_case.execute(principal)
    return ok(UserPayload.model_validate(user), request_id=request_id)


@router.patch("/users/me", response_model=Envelope[UserPayload])
@inject
async def update_me(
    payload: UpdateProfileRequest,
    use_case: UpdateProfileUseCase = Depends(Provide[Container.update_profile_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[UserPayload]:
    user = await use_case.execute(
        principal,
        UpdateProfileCommand(display_name=payload.display_name, avatar_key=payload.avatar_key),
    )
    return ok(UserPayload.model_validate(user), request_id=request_id)


@router.post("/users/me/password", status_code=status.HTTP_202_ACCEPTED)
@inject
async def change_password(
    payload: ChangePasswordRequest,
    use_case: ChangePasswordUseCase = Depends(Provide[Container.change_password_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[dict[str, str]]:
    """Changing the password revokes every existing session."""
    await use_case.execute(
        principal,
        ChangePasswordCommand(
            current_password=payload.current_password, new_password=payload.new_password
        ),
    )
    return ok({"status": "password_changed"}, request_id=request_id)


@router.get("/api-keys", response_model=Envelope[PagePayload[ApiKeyPayload]])
@inject
async def list_api_keys(
    use_case: ListApiKeysUseCase = Depends(Provide[Container.list_api_keys_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[ApiKeyPayload]]:
    keys = await use_case.execute(principal)
    payload = PagePayload[ApiKeyPayload](
        items=[ApiKeyPayload.model_validate(key) for key in keys],
        total=len(keys),
        limit=len(keys),
        offset=0,
    )
    return ok(payload, request_id=request_id)


@router.post("/api-keys", response_model=Envelope[ApiKeyIssuedPayload], status_code=201)
@inject
async def create_api_key(
    payload: CreateApiKeyRequest,
    use_case: CreateApiKeyUseCase = Depends(Provide[Container.create_api_key_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[ApiKeyIssuedPayload]:
    """The plaintext key is returned exactly once."""
    issued = await use_case.execute(
        principal,
        CreateApiKeyCommand(name=payload.name, expires_in_days=payload.expires_in_days),
    )
    return ok(ApiKeyIssuedPayload.model_validate(issued), request_id=request_id)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def revoke_api_key(
    key_id: UUID,
    use_case: RevokeApiKeyUseCase = Depends(Provide[Container.revoke_api_key_use_case]),
    principal: Principal = Depends(get_principal),
) -> Response:
    await use_case.execute(principal, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
