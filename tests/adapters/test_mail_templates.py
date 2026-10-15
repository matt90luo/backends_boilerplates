"""Render every transactional template with the context the use cases produce.

The in-memory mailer never touches Jinja, so this test drives the real
``ConsoleMailer`` + ``TemplateRenderer`` (``StrictUndefined``) to catch typos in
the templates or in the context keys.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from dependency_injector import providers

from tests.conftest import AppContext
from tests.fakes.external import WEBHOOK_SIGNATURE, webhook_payload
from tinysaas.adapters.mail.console import ConsoleMailer
from tinysaas.adapters.mail.renderer import TemplateRenderer
from tinysaas.application.dto.commands import (
    RegisterUserCommand,
    RequestPasswordResetCommand,
    StartTopUpCommand,
)
from tinysaas.domain.access.policy import Principal

pytestmark = pytest.mark.asyncio


@pytest.fixture
def console_outbox(ctx: AppContext, tmp_path: Path) -> Path:
    ctx.container.mailer.override(
        providers.Object(
            ConsoleMailer(
                renderer=TemplateRenderer(),
                outbox_dir=str(tmp_path),
                from_address="Tiny SaaS <no-reply@tinysaas.test>",
                logger=ctx.container.logger(),
            )
        )
    )
    return tmp_path


async def test_every_template_renders(ctx: AppContext, console_outbox: Path) -> None:
    session = await ctx.container.register_user_use_case().execute(
        RegisterUserCommand(email="templates@example.com", password="Passw0rd!23")
    )
    await ctx.container.request_password_reset_use_case().execute(
        RequestPasswordResetCommand(email="templates@example.com")
    )

    principal = Principal(
        user_id=session.user.id,
        role=session.user.role,
        plan=session.user.plan,
        daily_quota=session.user.daily_quota,
    )
    ctx.seed_package(slug="starter", credits=100, amount_minor=500)
    checkout = await ctx.container.start_topup_use_case().execute(
        principal,
        StartTopUpCommand(package_slug="starter", idempotency_key="template-key"),
    )
    payload = webhook_payload(
        event_id="evt_template",
        topup_id=UUID(str(checkout.topup_id)),
        session_id=f"cs_test_{checkout.topup_id}",
    )
    await ctx.container.handle_topup_webhook_use_case().execute(payload, WEBHOOK_SIGNATURE)

    rendered = {
        path.name.split("-")[-1].removesuffix(".html"): path
        for path in console_outbox.glob("*.html")
    }
    assert set(rendered) == {"welcome", "verify_email", "password_reset", "credit_receipt"}

    welcome = rendered["welcome"].read_text(encoding="utf-8")
    assert "Tiny SaaS" in welcome
    assert "verify-email?token=" in welcome

    receipt = rendered["credit_receipt"].read_text(encoding="utf-8")
    assert "+100" in receipt
    assert "5.00 USD" in receipt

    reset = rendered["password_reset"].read_text(encoding="utf-8")
    assert "reset-password?token=" in reset
    assert "30 分钟" in reset
