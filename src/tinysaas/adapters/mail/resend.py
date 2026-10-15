"""Resend mailer (plain HTTPS API, no SDK dependency)."""

from __future__ import annotations

import httpx

from tinysaas.adapters.mail.renderer import TemplateRenderer
from tinysaas.application.errors import MailDeliveryError, PaymentConfigurationError
from tinysaas.application.ports.external import EmailMessage


class ResendMailer:
    """Adapter implementing :class:`Mailer` against ``api.resend.com``."""

    def __init__(
        self,
        *,
        renderer: TemplateRenderer,
        http_client: httpx.AsyncClient,
        api_key: str,
        from_address: str,
        base_url: str = "https://api.resend.com",
    ) -> None:
        self._renderer = renderer
        self._client = http_client
        self._api_key = api_key
        self._from = from_address
        self._base_url = base_url.rstrip("/")

    async def send(self, message: EmailMessage) -> None:
        if not self._api_key:
            raise PaymentConfigurationError("RESEND_API_KEY is not configured")
        html = self._renderer.render(message.template, message.context)
        try:
            response = await self._client.post(
                f"{self._base_url}/emails",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._from,
                    "to": [message.to],
                    "subject": message.subject,
                    "html": html,
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise MailDeliveryError(
                "邮件发送失败", details={"status": error.response.status_code}
            ) from error
        except httpx.HTTPError as error:
            raise MailDeliveryError("邮件服务不可用") from error
