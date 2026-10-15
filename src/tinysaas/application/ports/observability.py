"""Logging and error reporting ports."""

from __future__ import annotations

from typing import Protocol


class AppLogger(Protocol):
    """Minimal structured logging surface used by use cases."""

    def info(self, event: str, **kwargs: object) -> None: ...

    def warning(self, event: str, **kwargs: object) -> None: ...

    def error(self, event: str, **kwargs: object) -> None: ...

    def exception(self, event: str, **kwargs: object) -> None: ...


class Telemetry(Protocol):
    """Error reporting / tracing (Sentry in production, no-op otherwise)."""

    def capture_exception(self, error: BaseException, **context: object) -> None: ...

    def capture_message(self, message: str, **context: object) -> None: ...
