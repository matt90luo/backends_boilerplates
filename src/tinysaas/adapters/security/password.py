"""Argon2id password hasher."""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2PasswordHasher
from argon2.exceptions import Argon2Error


class Argon2PasswordHasher:
    """Adapter implementing :class:`PasswordHasher`."""

    def __init__(
        self, *, time_cost: int = 2, memory_cost: int = 65_536, parallelism: int = 2
    ) -> None:
        self._hasher = _Argon2PasswordHasher(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (Argon2Error, ValueError, TypeError):
            return False
