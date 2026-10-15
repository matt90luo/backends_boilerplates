"""HTTP tests for the credit loop, the dispatcher and log visibility."""

from __future__ import annotations

import base64
import json
from uuid import UUID

import httpx

from tests.conftest import AppContext, bearer, login_admin, register
from tests.fakes.external import WEBHOOK_SIGNATURE, webhook_payload
from tinysaas.domain.catalog.service import ExecMode


async def top_up(
    client: httpx.AsyncClient,
    ctx: AppContext,
    *,
    token: str,
    package_slug: str = "starter",
    key: str = "topup-key-1",
) -> dict:
    """Run the whole Checkout + webhook round trip for a package."""
    ctx.seed_package(slug=package_slug)
    response = await client.post(
        "/api/v1/billing/checkout",
        json={"package_slug": package_slug},
        headers={**bearer(token), "Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    checkout = response.json()["data"]

    payload = webhook_payload(
        event_id=f"evt_{key}",
        topup_id=UUID(checkout["topup_id"]),
        session_id=f"cs_test_{checkout['topup_id']}",
    )
    webhook = await client.post(
        "/api/v1/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": WEBHOOK_SIGNATURE},
    )
    assert webhook.status_code == 200, webhook.text
    return checkout


async def test_sync_execution_charges_credits_and_logs(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    ctx.seed_service(slug="echo", credit_cost=1)
    session = await register(client, email="payer@example.com")
    token = session["access_token"]
    user_id = session["user"]["id"]

    await top_up(client, ctx, token=token)
    assert ctx.balance_of(UUID(user_id)) == 100

    response = await client.post(
        "/api/v1/services/echo/execute",
        content=json.dumps({"text": "hi"}),
        headers={**bearer(token), "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert response.headers["X-Credits-Charged"] == "1"
    assert response.headers["X-Replayed"] == "false"

    assert ctx.balance_of(UUID(user_id)) == 99
    assert ctx.ledger_kinds(UUID(user_id)) == ["topup", "reserve", "settle"]
    assert ctx.executor.calls == ["echo"]

    logs = await client.get("/api/v1/me/invocations", headers=bearer(token))
    assert logs.status_code == 200
    items = logs.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "succeeded"
    assert items[0]["service_slug"] == "echo"
    assert items[0]["credits_charged"] == 1
    assert items[0]["latency_ms"] == 7


async def test_upstream_failure_refunds_credits(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="echo", credit_cost=4)
    session = await register(client, email="refund@example.com")
    token = session["access_token"]
    user_id = UUID(session["user"]["id"])
    await top_up(client, ctx, token=token)

    ctx.executor.ok = False
    ctx.executor.error_code = "UPSTREAM_FAILED"

    response = await client.post(
        "/api/v1/services/echo/execute",
        content=b"{}",
        headers={**bearer(token), "Content-Type": "application/json"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "UPSTREAM_FAILED"
    assert body["details"]["invocation_id"]

    assert ctx.balance_of(user_id) == 100
    assert ctx.wallet_of(user_id).reserved == 0
    assert ctx.ledger_kinds(user_id) == ["topup", "reserve", "refund"]

    logs = await client.get("/api/v1/me/invocations", headers=bearer(token))
    item = logs.json()["data"]["items"][0]
    assert item["status"] == "refunded"
    assert item["credits_refunded"] == 4


async def test_insufficient_credits_is_402(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="echo", credit_cost=5)
    session = await register(client, email="broke@example.com")

    response = await client.post(
        "/api/v1/services/echo/execute", content=b"{}", headers=bearer(session["access_token"])
    )
    assert response.status_code == 402
    assert response.json()["code"] == "INSUFFICIENT_CREDITS"
    assert ctx.ledger_kinds(UUID(session["user"]["id"])) == []


async def test_daily_quota_blocks_further_calls(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="echo", credit_cost=1)
    session = await register(client, email="quota@example.com")
    token = session["access_token"]
    await top_up(client, ctx, token=token)
    user_id = UUID(session["user"]["id"])
    ctx.store.users[user_id].daily_quota = 1

    first = await client.post("/api/v1/services/echo/execute", content=b"{}", headers=bearer(token))
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/services/echo/execute", content=b"{}", headers=bearer(token)
    )
    assert second.status_code == 429
    assert second.json()["code"] == "QUOTA_EXCEEDED"
    assert ctx.balance_of(user_id) == 99


async def test_execute_is_idempotent(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="echo", credit_cost=2)
    session = await register(client, email="idem@example.com")
    token = session["access_token"]
    user_id = UUID(session["user"]["id"])
    await top_up(client, ctx, token=token)

    headers = {**bearer(token), "Idempotency-Key": "call-1"}
    first = await client.post("/api/v1/services/echo/execute", content=b"{}", headers=headers)
    second = await client.post("/api/v1/services/echo/execute", content=b"{}", headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers["X-Invocation-Id"] == second.headers["X-Invocation-Id"]
    assert second.headers["X-Replayed"] == "true"
    assert ctx.balance_of(user_id) == 98
    assert len(ctx.executor.calls) == 1


async def test_async_task_runs_in_the_worker(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="slow-report", credit_cost=3, exec_mode=ExecMode.ASYNC)
    session = await register(client, email="async@example.com")
    token = session["access_token"]
    user_id = UUID(session["user"]["id"])
    await top_up(client, ctx, token=token)

    submitted = await client.post(
        "/api/v1/services/slow-report/tasks",
        content=json.dumps({"delay_seconds": 0.1}),
        headers={**bearer(token), "Content-Type": "application/json"},
    )
    assert submitted.status_code == 202, submitted.text
    task = submitted.json()["data"]
    assert task["status"] == "queued"
    assert ctx.balance_of(user_id) == 97  # reserved up front
    assert ctx.wallet_of(user_id).reserved == 3

    # The API never executed anything: the queued job is picked up by the worker.
    assert ctx.executor.calls == []
    job = ctx.queue.jobs[0]
    assert job.task_name == "tinysaas.execute_service_task"

    worker = ctx.container.run_service_task_use_case()
    view = await worker.execute(
        UUID(str(job.payload["invocation_id"])),
        payload=base64.b64decode(str(job.payload["body_b64"])),
        content_type=str(job.payload["content_type"]),
    )
    assert view.status.value == "succeeded"
    assert ctx.balance_of(user_id) == 97
    assert ctx.wallet_of(user_id).reserved == 0
    assert ctx.ledger_kinds(user_id) == ["topup", "reserve", "settle"]

    polled = await client.get(f"/api/v1/tasks/{task['task_id']}", headers=bearer(token))
    assert polled.json()["data"]["status"] == "succeeded"


async def test_async_endpoint_rejects_sync_service(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    ctx.seed_service(slug="echo", credit_cost=1, exec_mode=ExecMode.SYNC)
    session = await register(client, email="mode@example.com")
    await top_up(client, ctx, token=session["access_token"])

    response = await client.post(
        "/api/v1/services/echo/tasks", content=b"{}", headers=bearer(session["access_token"])
    )
    assert response.status_code == 409
    assert response.json()["code"] == "EXEC_MODE_MISMATCH"


async def test_users_only_see_their_own_logs(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="echo", credit_cost=1)
    owner = await register(client, email="owner@example.com")
    await top_up(client, ctx, token=owner["access_token"])
    await client.post(
        "/api/v1/services/echo/execute", content=b"{}", headers=bearer(owner["access_token"])
    )
    invocation_id = (
        await client.get("/api/v1/me/invocations", headers=bearer(owner["access_token"]))
    ).json()["data"]["items"][0]["id"]

    stranger = await register(client, email="stranger@example.com")
    assert (
        await client.get("/api/v1/me/invocations", headers=bearer(stranger["access_token"]))
    ).json()["data"]["total"] == 0

    forbidden = await client.get(
        f"/api/v1/me/invocations/{invocation_id}", headers=bearer(stranger["access_token"])
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"


async def test_admin_sees_any_user_logs(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_service(slug="echo", credit_cost=1)
    admin = await login_admin(client, ctx)
    member = await register(client, email="watched@example.com")
    await top_up(client, ctx, token=member["access_token"], key="admin-visible")
    await client.post(
        "/api/v1/services/echo/execute", content=b"{}", headers=bearer(member["access_token"])
    )

    admin_headers = bearer(admin["access_token"])
    per_user = await client.get(
        f"/api/v1/admin/users/{member['user']['id']}/invocations", headers=admin_headers
    )
    assert per_user.status_code == 200
    assert per_user.json()["data"]["total"] == 1

    global_logs = await client.get(
        "/api/v1/admin/invocations",
        params={"service_slug": "echo", "status": "succeeded"},
        headers=admin_headers,
    )
    assert global_logs.json()["data"]["total"] == 1

    detail = await client.get(f"/api/v1/admin/users/{member['user']['id']}", headers=admin_headers)
    assert detail.json()["data"]["balance"] == 99
    assert detail.json()["data"]["user"]["email"] == "watched@example.com"


async def test_admin_service_crud(client: httpx.AsyncClient, ctx: AppContext) -> None:
    admin = await login_admin(client, ctx)
    headers = bearer(admin["access_token"])

    created = await client.post(
        "/api/v1/admin/services",
        json={
            "slug": "bg-remove",
            "name": "Background remover",
            "credit_cost": 5,
            "exec_mode": "sync",
            "upstream_url": "http://bg-worker:8080/predict",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    service_id = created.json()["data"]["id"]

    updated = await client.patch(
        f"/api/v1/admin/services/{service_id}",
        json={"credit_cost": 7, "clear_upstream_url": True},
        headers=headers,
    )
    assert updated.json()["data"]["credit_cost"] == 7
    assert updated.json()["data"]["upstream_url"] is None

    deactivated = await client.delete(f"/api/v1/admin/services/{service_id}", headers=headers)
    assert deactivated.json()["data"]["is_active"] is False

    catalogue = await client.get("/api/v1/services", headers=headers)
    assert catalogue.json()["data"]["total"] == 0

    # The admin catalogue still shows the soft deleted row.
    admin_catalogue = await client.get("/api/v1/admin/services", headers=headers)
    assert admin_catalogue.json()["data"]["total"] == 1


async def test_inactive_service_cannot_be_invoked(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    ctx.seed_service(slug="echo", credit_cost=1, is_active=False)
    session = await register(client, email="inactive@example.com")
    response = await client.post(
        "/api/v1/services/echo/execute", content=b"{}", headers=bearer(session["access_token"])
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SERVICE_INACTIVE"


async def test_unknown_service_is_404(client: httpx.AsyncClient, ctx: AppContext) -> None:
    session = await register(client, email="missing@example.com")
    response = await client.post(
        "/api/v1/services/nope/execute", content=b"{}", headers=bearer(session["access_token"])
    )
    assert response.status_code == 404
    assert response.json()["code"] == "SERVICE_NOT_FOUND"


async def test_presigned_upload_and_ownership(client: httpx.AsyncClient, ctx: AppContext) -> None:
    session = await register(client, email="files@example.com")
    headers = bearer(session["access_token"])

    presigned = await client.post(
        "/api/v1/files/presign",
        json={"purpose": "avatar", "content_type": "image/png", "size": 1024},
        headers=headers,
    )
    assert presigned.status_code == 200, presigned.text
    data = presigned.json()["data"]
    assert data["key"].startswith(f"users/{session['user']['id']}/avatar/")
    assert "verb=put" in data["url"]

    updated = await client.patch(
        "/api/v1/users/me", json={"avatar_key": data["key"]}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["avatar_key"] == data["key"]

    download = await client.post(
        "/api/v1/files/presign/download", json={"key": data["key"]}, headers=headers
    )
    assert download.status_code == 200
    assert "verb=get" in download.json()["data"]["url"]

    stranger = await register(client, email="nosy@example.com")
    denied = await client.post(
        "/api/v1/files/presign/download",
        json={"key": data["key"]},
        headers=bearer(stranger["access_token"]),
    )
    assert denied.status_code == 403

    wrong_owner = await client.patch(
        "/api/v1/users/me",
        json={"avatar_key": data["key"]},
        headers=bearer(stranger["access_token"]),
    )
    assert wrong_owner.status_code == 422

    rejected = await client.post(
        "/api/v1/files/presign",
        json={"purpose": "avatar", "content_type": "application/x-msdownload", "size": 10},
        headers=headers,
    )
    assert rejected.status_code == 422


async def test_billing_checkout_requires_idempotency_key(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    ctx.seed_package()
    session = await register(client, email="nokey@example.com")
    response = await client.post(
        "/api/v1/billing/checkout",
        json={"package_slug": "starter"},
        headers=bearer(session["access_token"]),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_health_and_readiness(client: httpx.AsyncClient, ctx: AppContext) -> None:
    live = await client.get("/healthz")
    assert live.status_code == 200
    assert live.json()["data"]["status"] == "ok"
    assert live.headers["X-Request-ID"]

    ready = await client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["data"] == {"status": "ok", "components": {}}


async def test_openapi_schema_is_exposed(client: httpx.AsyncClient, ctx: AppContext) -> None:
    schema = await client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/v1/services/{slug}/execute" in paths
    assert "/api/v1/admin/users/{user_id}" in paths
