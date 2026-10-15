"""Authentication and session endpoints."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, Response, status

from tinysaas.adapters.web.cookies import CookiePolicy
from tinysaas.adapters.web.deps import get_principal, get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, PagePayload, ok
from tinysaas.adapters.web.schemas.payloads import AuthSessionPayload, SessionPayload
from tinysaas.adapters.web.schemas.requests import (
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    VerifyEmailRequest,
)
from tinysaas.application.dto.commands import (
    LoginCommand,
    LogoutCommand,
    RefreshSessionCommand,
    RegisterUserCommand,
    RequestPasswordResetCommand,
    ResetPasswordCommand,
    VerifyEmailCommand,
)
from tinysaas.application.use_cases.auth import (
    ListSessionsUseCase,
    LoginUseCase,
    LogoutAllUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
    RegisterUserUseCase,
    RequestPasswordResetUseCase,
    ResetPasswordUseCase,
    RevokeSessionUseCase,
    VerifyEmailUseCase,
)
from tinysaas.containers.container import Container
from tinysaas.domain.access.policy import Principal

router = APIRouter(prefix="/auth", tags=["auth"])


async def optional_principal(request: Request) -> Principal | None:
    """Logout works for anonymous callers too, so it cannot require auth."""
    principal: Principal | None = getattr(request.state, "principal", None)
    return principal


@router.post("/register", response_model=Envelope[AuthSessionPayload], status_code=201)
@inject
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    use_case: RegisterUserUseCase = Depends(Provide[Container.register_user_use_case]),
    cookies: CookiePolicy = Depends(Provide[Container.cookie_policy]),
    request_id: str = Depends(get_request_id),
) -> Envelope[AuthSessionPayload]:
    """Create an account, its wallet and an initial session."""
    session = await use_case.execute(
        RegisterUserCommand(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.client.host if request.client else None,
        )
    )
    cookies.set(response, session.refresh_token, max_age=session.refresh_expires_in)
    return ok(AuthSessionPayload.model_validate(session), request_id=request_id)


@router.post("/login", response_model=Envelope[AuthSessionPayload])
@inject
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    use_case: LoginUseCase = Depends(Provide[Container.login_use_case]),
    cookies: CookiePolicy = Depends(Provide[Container.cookie_policy]),
    request_id: str = Depends(get_request_id),
) -> Envelope[AuthSessionPayload]:
    session = await use_case.execute(
        LoginCommand(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.client.host if request.client else None,
        )
    )
    cookies.set(response, session.refresh_token, max_age=session.refresh_expires_in)
    return ok(AuthSessionPayload.model_validate(session), request_id=request_id)


@router.post("/refresh", response_model=Envelope[AuthSessionPayload])
@inject
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    use_case: RefreshSessionUseCase = Depends(Provide[Container.refresh_session_use_case]),
    cookies: CookiePolicy = Depends(Provide[Container.cookie_policy]),
    request_id: str = Depends(get_request_id),
) -> Envelope[AuthSessionPayload]:
    """Rotate the refresh token; replaying an old token revokes the family."""
    token = payload.refresh_token or request.cookies.get(cookies.name) or ""
    session = await use_case.execute(
        RefreshSessionCommand(refresh_token=token, user_agent=request.headers.get("User-Agent"))
    )
    cookies.set(response, session.refresh_token, max_age=session.refresh_expires_in)
    return ok(AuthSessionPayload.model_validate(session), request_id=request_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def logout(
    payload: LogoutRequest,
    request: Request,
    response: Response,
    use_case: LogoutUseCase = Depends(Provide[Container.logout_use_case]),
    logout_all: LogoutAllUseCase = Depends(Provide[Container.logout_all_use_case]),
    cookies: CookiePolicy = Depends(Provide[Container.cookie_policy]),
    principal: Principal | None = Depends(optional_principal),
) -> Response:
    """Revoke the presented refresh token (and optionally every session)."""
    token = payload.refresh_token or request.cookies.get(cookies.name) or ""
    if token:
        await use_case.execute(LogoutCommand(refresh_token=token))
    if payload.all_sessions and principal is not None:
        await logout_all.execute(principal)
    cookies.clear(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions", response_model=Envelope[PagePayload[SessionPayload]])
@inject
async def list_sessions(
    use_case: ListSessionsUseCase = Depends(Provide[Container.list_sessions_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[SessionPayload]]:
    sessions = await use_case.execute(principal)
    payload = PagePayload[SessionPayload](
        items=[SessionPayload.model_validate(item) for item in sessions],
        total=len(sessions),
        limit=len(sessions),
        offset=0,
    )
    return ok(payload, request_id=request_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def revoke_session(
    session_id: UUID,
    use_case: RevokeSessionUseCase = Depends(Provide[Container.revoke_session_use_case]),
    principal: Principal = Depends(get_principal),
) -> Response:
    await use_case.execute(principal, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/verify-email", status_code=status.HTTP_202_ACCEPTED)
@inject
async def verify_email(
    payload: VerifyEmailRequest,
    use_case: VerifyEmailUseCase = Depends(Provide[Container.verify_email_use_case]),
    request_id: str = Depends(get_request_id),
) -> Envelope[dict[str, str]]:
    await use_case.execute(VerifyEmailCommand(token=payload.token))
    return ok({"status": "verified"}, request_id=request_id)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
@inject
async def request_password_reset(
    payload: PasswordResetRequest,
    use_case: RequestPasswordResetUseCase = Depends(
        Provide[Container.request_password_reset_use_case]
    ),
    request_id: str = Depends(get_request_id),
) -> Envelope[dict[str, str]]:
    """Always 202: the response must not reveal whether the email exists."""
    await use_case.execute(RequestPasswordResetCommand(email=payload.email))
    return ok({"status": "accepted"}, request_id=request_id)


@router.post("/password-reset/confirm", status_code=status.HTTP_202_ACCEPTED)
@inject
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    use_case: ResetPasswordUseCase = Depends(Provide[Container.reset_password_use_case]),
    request_id: str = Depends(get_request_id),
) -> Envelope[dict[str, str]]:
    await use_case.execute(
        ResetPasswordCommand(token=payload.token, new_password=payload.new_password)
    )
    return ok({"status": "password_reset"}, request_id=request_id)
