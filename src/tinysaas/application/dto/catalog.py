"""Service catalogue DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tinysaas.domain.catalog.service import ExecMode, Service


@dataclass(frozen=True, slots=True)
class ServiceView:
    id: UUID
    slug: str
    name: str
    description: str | None
    credit_cost: int
    exec_mode: ExecMode
    upstream_url: str | None
    timeout_secs: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_service(cls, service: Service) -> ServiceView:
        return cls(
            id=service.id,
            slug=service.slug,
            name=service.name,
            description=service.description,
            credit_cost=service.credit_cost,
            exec_mode=service.exec_mode,
            upstream_url=service.upstream_url,
            timeout_secs=service.timeout_secs,
            is_active=service.is_active,
            created_at=service.created_at,
            updated_at=service.updated_at,
        )
