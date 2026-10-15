"""A controllable clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

DEFAULT_START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or DEFAULT_START

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int = 0, minutes: int = 0, hours: int = 0, days: int = 0) -> None:
        self.current += timedelta(seconds=seconds, minutes=minutes, hours=hours, days=days)
