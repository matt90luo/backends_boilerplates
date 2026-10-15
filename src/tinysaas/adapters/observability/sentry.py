"""Sentry error reporting (disabled unless a DSN is configured)."""

from __future__ import annotations

import sentry_sdk

from tinysaas.infrastructure.config import Settings


def init_sentry(settings: Settings) -> None:
    """Initialise Sentry once per process; a no-op without ``SENTRY_DSN``."""
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )


class SentryTelemetry:
    """Adapter implementing :class:`Telemetry`."""

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled

    def capture_exception(self, error: BaseException, **context: object) -> None:
        if not self._enabled:
            return
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(error)

    def capture_message(self, message: str, **context: object) -> None:
        if not self._enabled:
            return
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_message(message)
