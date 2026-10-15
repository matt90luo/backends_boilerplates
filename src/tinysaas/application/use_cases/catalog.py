"""Service catalogue use cases: the tool registry CRUD."""

from __future__ import annotations

from uuid import UUID

from tinysaas.application.dto.catalog import ServiceView
from tinysaas.application.dto.commands import (
    CreateServiceCommand,
    ListServicesQuery,
    UpdateServiceCommand,
)
from tinysaas.application.dto.common import Page
from tinysaas.application.errors import ServiceNotFound, ServiceSlugTaken
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.persistence import UnitOfWorkFactory
from tinysaas.domain.access.policy import AccessPolicy, Principal
from tinysaas.domain.catalog.service import Service


class CreateServiceUseCase:
    """Register a new tool. Publishing it needs no gateway restart."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal, command: CreateServiceCommand) -> ServiceView:
        AccessPolicy.ensure_admin(principal)
        service = Service.create(
            slug=command.slug,
            name=command.name,
            description=command.description,
            credit_cost=command.credit_cost,
            exec_mode=command.exec_mode,
            upstream_url=command.upstream_url,
            timeout_secs=command.timeout_secs,
            is_active=command.is_active,
            now=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            if await uow.services.get_by_slug(service.slug) is not None:
                raise ServiceSlugTaken("该 slug 已被占用", details={"field": "slug"})
            await uow.services.add(service)
            await uow.commit()
        return ServiceView.from_service(service)


class UpdateServiceUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, principal: Principal, service_id: UUID, command: UpdateServiceCommand
    ) -> ServiceView:
        AccessPolicy.ensure_admin(principal)
        async with self._uow_factory() as uow:
            service = await uow.services.get(service_id)
            if service is None:
                raise ServiceNotFound("服务不存在")
            service.update(
                name=command.name,
                description=command.description,
                credit_cost=command.credit_cost,
                exec_mode=command.exec_mode,
                upstream_url=command.upstream_url,
                clear_upstream_url=command.clear_upstream_url,
                timeout_secs=command.timeout_secs,
                is_active=command.is_active,
                now=self._clock.now(),
            )
            await uow.services.update(service)
            await uow.commit()
        return ServiceView.from_service(service)


class DeactivateServiceUseCase:
    """Soft delete: the log history stays intact."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal, service_id: UUID) -> ServiceView:
        AccessPolicy.ensure_admin(principal)
        async with self._uow_factory() as uow:
            service = await uow.services.get(service_id)
            if service is None:
                raise ServiceNotFound("服务不存在")
            service.deactivate(now=self._clock.now())
            await uow.services.update(service)
            await uow.commit()
        return ServiceView.from_service(service)


class ListServicesUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, query: ListServicesQuery) -> Page[ServiceView]:
        include_inactive = query.include_inactive and principal.is_admin
        async with self._uow_factory() as uow:
            services, total = await uow.services.list(
                include_inactive=include_inactive, limit=query.limit, offset=query.offset
            )
        return Page(
            items=[ServiceView.from_service(service) for service in services],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )


class GetServiceUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal, slug: str) -> ServiceView:
        async with self._uow_factory() as uow:
            service = await uow.services.get_by_slug(slug)
        if service is None:
            raise ServiceNotFound("服务不存在")
        AccessPolicy.ensure_can_invoke(principal, service)
        return ServiceView.from_service(service)
