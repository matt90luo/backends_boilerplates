"""structlog configuration and the application logger adapter."""

from __future__ import annotations

import logging
import sys

import structlog

from tinysaas.infrastructure.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog (and route stdlib logs through it)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    for noisy in ("uvicorn.access", "asyncio", "botocore", "httpx"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


class StructlogLogger:
    """Adapter implementing :class:`AppLogger` on top of structlog."""

    def __init__(self, component: str = "tinysaas") -> None:
        self._logger = structlog.get_logger(component)

    def info(self, event: str, **kwargs: object) -> None:
        self._logger.info(event, **kwargs)

    def warning(self, event: str, **kwargs: object) -> None:
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._logger.error(event, **kwargs)

    def exception(self, event: str, **kwargs: object) -> None:
        self._logger.exception(event, **kwargs)
