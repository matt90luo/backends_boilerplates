"""Provider webhooks (signature verified, no authentication middleware)."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, Request

from tinysaas.adapters.web.deps import get_request_id
from tinysaas.adapters.web.schemas.envelope import Envelope, ok
from tinysaas.application.use_cases.billing import HandleTopUpWebhookUseCase
from tinysaas.containers.container import Container

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe", response_model=Envelope[dict[str, bool]])
@inject
async def stripe_webhook(
    request: Request,
    use_case: HandleTopUpWebhookUseCase = Depends(Provide[Container.handle_topup_webhook_use_case]),
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    request_id: str = Depends(get_request_id),
) -> Envelope[dict[str, bool]]:
    """Credit the wallet exactly once per paid Checkout Session."""
    payload = await request.body()
    handled = await use_case.execute(payload, stripe_signature)
    return ok({"received": True, "handled": handled}, request_id=request_id)
