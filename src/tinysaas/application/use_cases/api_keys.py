"""API key management use cases."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from tinysaas.application.dto.commands import CreateApiKeyCommand
from tinysaas.application.dto.identity import ApiKeyIssued, ApiKeyView
from tinysaas.application.errors import ApiKeyNotFound
from tinysaas.application.options import AppOptions
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.persistence import UnitOfWorkFactory
from tinysaas.application.ports.security import ApiKeyService
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.identity.api_key import ApiKey


class CreateApiKeyUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        api_key_service: ApiKeyService,
        options: AppOptions,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._api_key_service = api_key_service
        self._options = options
        self._clock = clock

    async def execute(self, principal: Principal, command: CreateApiKeyCommand) -> ApiKeyIssued:
        material = self._api_key_service.generate()
        ttl = (
            timedelta(days=command.expires_in_days)
            if command.expires_in_days
            else timedelta(days=self._options.session.api_key_ttl_days)
        )
        api_key = ApiKey.issue(
            user_id=principal.user_id,
            name=command.name,
            prefix=material.prefix,
            key_hash=material.key_hash,
            ttl=ttl,
            now=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.api_keys.add(api_key)
            await uow.commit()
        return ApiKeyIssued(api_key=ApiKeyView.from_api_key(api_key), plaintext=material.plaintext)


class ListApiKeysUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal) -> list[ApiKeyView]:
        async with self._uow_factory() as uow:
            keys = await uow.api_keys.list_for_user(principal.user_id)
        return [ApiKeyView.from_api_key(key) for key in keys]


class RevokeApiKeyUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal, key_id: UUID) -> None:
        async with self._uow_factory() as uow:
            api_key = await uow.api_keys.get(key_id)
            if api_key is None or api_key.user_id != principal.user_id:
                raise ApiKeyNotFound("API Key 不存在")
            api_key.revoke(now=self._clock.now())
            await uow.api_keys.update(api_key)
            await uow.commit()
