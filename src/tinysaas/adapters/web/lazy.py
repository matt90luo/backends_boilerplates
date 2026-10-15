"""Resolve a container provider on first use.

Middleware is built while the app object is created, i.e. *before* the lifespan
has initialised the process resources, so providers that depend on those
resources must be resolved lazily (on the first request instead).
"""

from __future__ import annotations

from collections.abc import Callable


class Lazy[T]:
    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._value: T | None = None

    def __call__(self) -> T:
        if self._value is None:
            self._value = self._factory()
        return self._value
