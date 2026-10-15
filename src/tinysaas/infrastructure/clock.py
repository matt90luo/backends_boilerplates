"""Time and UUID sources."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4


class SystemClock:
    """Adapter implementing :class:`Clock`."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator:
    """Adapter implementing :class:`IdGenerator`."""

    def new_id(self) -> UUID:
        return uuid4()
