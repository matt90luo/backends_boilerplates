"""Credit wallet and Stripe Checkout endpoints."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header

from tinysaas.adapters.web.deps import get_pagination, get_principal, get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, PagePayload, ok
from tinysaas.adapters.web.schemas.payloads import (
    CheckoutPayload,
    LedgerEntryPayload,
    PackagePayload,
    TopUpPayload,
    WalletPayload,
)
from tinysaas.adapters.web.schemas.requests import Pagination, StartTopUpRequest
from tinysaas.application.dto.commands import ListLedgerQuery, StartTopUpCommand
from tinysaas.application.use_cases.billing import (
    GetTopUpUseCase,
    GetWalletUseCase,
    ListCreditPackagesUseCase,
    ListLedgerUseCase,
    StartTopUpUseCase,
)
from tinysaas.containers.container import Container
from tinysaas.domain.access.policy import Principal

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/packages", response_model=Envelope[PagePayload[PackagePayload]])
@inject
async def list_packages(
    use_case: ListCreditPackagesUseCase = Depends(Provide[Container.list_packages_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[PackagePayload]]:
    packages = await use_case.execute()
    payload = PagePayload[PackagePayload](
        items=[PackagePayload.model_validate(item) for item in packages],
        total=len(packages),
        limit=len(packages),
        offset=0,
    )
    return ok(payload, request_id=request_id)


@router.post("/checkout", response_model=Envelope[CheckoutPayload])
@inject
async def start_checkout(
    payload: StartTopUpRequest,
    use_case: StartTopUpUseCase = Depends(Provide[Container.start_topup_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
) -> Envelope[CheckoutPayload]:
    """Create (or replay) a Stripe Checkout Session for a credit package."""
    checkout = await use_case.execute(
        principal,
        StartTopUpCommand(package_slug=payload.package_slug, idempotency_key=idempotency_key),
    )
    return ok(CheckoutPayload.model_validate(checkout), request_id=request_id)


@router.get("/wallet", response_model=Envelope[WalletPayload])
@inject
async def get_wallet(
    use_case: GetWalletUseCase = Depends(Provide[Container.get_wallet_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[WalletPayload]:
    wallet = await use_case.execute(principal)
    return ok(WalletPayload.model_validate(wallet), request_id=request_id)


@router.get("/ledger", response_model=Envelope[PagePayload[LedgerEntryPayload]])
@inject
async def list_ledger(
    use_case: ListLedgerUseCase = Depends(Provide[Container.list_ledger_use_case]),
    principal: Principal = Depends(get_principal),
    pagination: Pagination = Depends(get_pagination),
    request_id: str = Depends(get_request_id),
) -> Envelope[PagePayload[LedgerEntryPayload]]:
    page = await use_case.execute(
        principal, ListLedgerQuery(limit=pagination.limit, offset=pagination.offset)
    )
    payload = PagePayload[LedgerEntryPayload](
        items=[LedgerEntryPayload.model_validate(entry) for entry in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)


@router.get("/topups/{topup_id}", response_model=Envelope[TopUpPayload])
@inject
async def get_topup(
    topup_id: UUID,
    use_case: GetTopUpUseCase = Depends(Provide[Container.get_topup_use_case]),
    principal: Principal = Depends(get_principal),
    request_id: str = Depends(get_request_id),
) -> Envelope[TopUpPayload]:
    topup = await use_case.execute(principal, topup_id)
    return ok(TopUpPayload.model_validate(topup), request_id=request_id)
