"""Console/outbox mailer: writes rendered emails to disk (development)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tinysaas.adapters.mail.renderer import TemplateRenderer
from tinysaas.application.ports.external import EmailMessage
from tinysaas.application.ports.observability import AppLogger


class ConsoleMailer:
    """Adapter implementing :class:`Mailer` without any network dependency."""

    def __init__(
        self,
        *,
        renderer: TemplateRenderer,
        outbox_dir: str,
        from_address: str,
        logger: AppLogger,
    ) -> None:
        self._renderer = renderer
        self._outbox = Path(outbox_dir)
        self._from = from_address
        self._logger = logger

    async def send(self, message: EmailMessage) -> None:
        html = self._renderer.render(message.template, message.context)
        self._outbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        safe_to = message.to.replace("@", "_at_")
        path = self._outbox / f"{stamp}-{safe_to}-{message.template}.html"
        path.write_text(html, encoding="utf-8")
        self._logger.info(
            "email_written_to_outbox",
            to=message.to,
            template=message.template,
            path=str(path),
            sender=self._from,
        )
