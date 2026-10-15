"""Current user profile use cases."""

from __future__ import annotations

from tinysaas.application.dto.commands import ChangePasswordCommand, UpdateProfileCommand
from tinysaas.application.dto.identity import UserView
from tinysaas.application.errors import InvalidCredentials, UserNotFound
from tinysaas.application.ports.clock import Clock
from tinysaas.application.ports.persistence import UnitOfWorkFactory
from tinysaas.application.ports.security import PasswordHasher
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.errors import ValidationError
from tinysaas.domain.identity.password import validate_password


class GetProfileUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, principal: Principal) -> UserView:
        async with self._uow_factory() as uow:
            user = await uow.users.get(principal.user_id)
        if user is None:
            raise UserNotFound("用户不存在")
        return UserView.from_user(user)


class UpdateProfileUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, principal: Principal, command: UpdateProfileCommand) -> UserView:
        if command.avatar_key is not None:
            expected_prefix = f"users/{principal.user_id}/"
            if command.avatar_key and not command.avatar_key.startswith(expected_prefix):
                raise ValidationError("头像必须上传到自己的目录下", details={"field": "avatar_key"})
        async with self._uow_factory() as uow:
            user = await uow.users.get(principal.user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            user.update_profile(
                display_name=command.display_name,
                avatar_key=command.avatar_key,
                now=self._clock.now(),
            )
            await uow.users.update(user)
            await uow.commit()
        return UserView.from_user(user)


class ChangePasswordUseCase:
    """Change the password and drop every existing session."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._clock = clock

    async def execute(self, principal: Principal, command: ChangePasswordCommand) -> None:
        validate_password(command.new_password)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            user = await uow.users.get(principal.user_id)
            if user is None:
                raise UserNotFound("用户不存在")
            if not self._password_hasher.verify(user.password_hash, command.current_password):
                raise InvalidCredentials("当前密码不正确")
            user.change_password_hash(self._password_hasher.hash(command.new_password), now=now)
            await uow.users.update(user)
            await uow.refresh_tokens.revoke_all_for_user(user.id, now=now)
            await uow.commit()
