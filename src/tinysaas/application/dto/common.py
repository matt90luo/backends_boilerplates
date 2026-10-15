"""Shared DTO helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Page[T]:
    """A slice of a collection plus the total number of matching rows."""

    items: Sequence[T]
    total: int
    limit: int
    offset: int

    def map[R](self, transform: Callable[[T], R]) -> Page[R]:
        return Page(
            items=[transform(item) for item in self.items],
            total=self.total,
            limit=self.limit,
            offset=self.offset,
        )
