"""The standard response envelope shared by every endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Meta(BaseModel):
    request_id: str | None = None


class Envelope[T](BaseModel):
    """Success shape: ``{"success": true, "data": ..., "meta": {...}}``."""

    success: bool = True
    data: T
    meta: Meta | None = None


class ErrorEnvelope(BaseModel):
    """Failure shape documented in the README."""

    success: bool = False
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class PagePayload[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class Payload(BaseModel):
    """Base class for response payloads built from application DTOs."""

    model_config = ConfigDict(from_attributes=True)


def ok[T](data: T, *, request_id: str | None = None) -> Envelope[T]:
    return Envelope[T](data=data, meta=Meta(request_id=request_id) if request_id else None)


def page_payload(
    page: Any, item_model: type[Payload], *, request_id: str | None = None
) -> Envelope[Any]:
    payload = PagePayload(
        items=[item_model.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(payload, request_id=request_id)
