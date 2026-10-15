"""End-to-end HTTP tests for registration, sessions and rate limiting."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import (
    ADMIN_PASSWORD,
    TEST_PASSWORD,
    AppContext,
    bearer,
    login,
    login_admin,
    register,
)

pytestmark = pytest.mark.asyncio


async def test_register_login_and_me(client: httpx.AsyncClient) -> None:
    session = await register(client, email="user@example.com")

    assert session["token_type"] == "Bearer"
    assert session["user"]["email"] == "user@example.com"
    assert session["user"]["daily_quota"] == 20

    me = await client.get("/api/v1/users/me", headers=bearer(session["access_token"]))
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "user@example.com"

    again = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": TEST_PASSWORD},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "EMAIL_TAKEN"

    signed_in = await login(client, email="user@example.com")
    assert signed_in["access_token"] != session["access_token"]


async def test_register_rejects_weak_password(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": "weak@example.com", "password": "abcdefgh"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "WEAK_PASSWORD"
    assert body["success"] is False
    assert "request_id" in body


async def test_login_with_wrong_password_is_401(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_user(email="known@example.com", password=TEST_PASSWORD)
    response = await client.post(
        "/api/v1/auth/login", json={"email": "known@example.com", "password": "WrongPass1"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_disabled_account_cannot_login(client: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.seed_user(email="off@example.com", password=TEST_PASSWORD, is_active=False)
    response = await client.post(
        "/api/v1/auth/login", json={"email": "off@example.com", "password": TEST_PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "USER_DISABLED"


async def test_refresh_rotates_and_detects_reuse(client: httpx.AsyncClient) -> None:
    session = await register(client, email="rotate@example.com")
    first_refresh = session["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200
    second_refresh = rotated.json()["data"]["refresh_token"]
    assert second_refresh != first_refresh

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401
    assert replay.json()["code"] == "AUTH_REFRESH_REUSED"

    # Reuse detection revokes the whole family, so the rotated token dies too.
    after_family_revocation = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second_refresh}
    )
    assert after_family_revocation.status_code == 401


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient) -> None:
    session = await register(client, email="logout@example.com")
    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": session["refresh_token"]}
    )
    assert logout.status_code == 204
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    assert refreshed.status_code == 401


async def test_sessions_are_listed_and_revocable(client: httpx.AsyncClient) -> None:
    session = await register(client, email="sessions@example.com")
    headers = bearer(session["access_token"])

    listed = await client.get("/api/v1/auth/sessions", headers=headers)
    assert listed.status_code == 200
    sessions = listed.json()["data"]["items"]
    assert len(sessions) == 1

    revoked = await client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=headers)
    assert revoked.status_code == 204
    listed_again = await client.get("/api/v1/auth/sessions", headers=headers)
    assert listed_again.json()["data"]["items"] == []


async def test_missing_token_is_401_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "code": "AUTH_REQUIRED",
        "message": "需要登录",
        "details": {},
        "request_id": response.headers["X-Request-ID"],
    }


async def test_password_reset_flow_sends_mail(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await register(client, email="reset@example.com")
    ctx.mailer.messages.clear()

    requested = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}
    )
    assert requested.status_code == 202
    assert "password_reset" in ctx.mailer.templates()

    unknown = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"}
    )
    assert unknown.status_code == 202
    assert ctx.mailer.templates().count("password_reset") == 1


async def test_email_verification_marks_the_account(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    await register(client, email="verify@example.com")
    assert "welcome" in ctx.mailer.templates()
    assert "verify_email" in ctx.mailer.templates()
    context = ctx.mailer.messages[-1].context
    token = str(context["verify_url"]).split("token=")[-1]

    verified = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 202

    reused = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert reused.status_code == 401
    assert reused.json()["code"] == "AUTH_INVALID_TOKEN"


async def test_login_endpoint_is_rate_limited(client: httpx.AsyncClient, ctx: AppContext) -> None:
    limited = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert limited.status_code == 401

    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
        )
    blocked = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    assert "Retry-After" in blocked.headers


async def test_api_key_can_authenticate(client: httpx.AsyncClient, ctx: AppContext) -> None:
    session = await register(client, email="apikey@example.com")
    issued = await client.post(
        "/api/v1/api-keys", json={"name": "ci"}, headers=bearer(session["access_token"])
    )
    assert issued.status_code == 201
    plaintext = issued.json()["data"]["plaintext"]

    me = await client.get("/api/v1/users/me", headers={"X-API-Key": plaintext})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "apikey@example.com"

    key_id = issued.json()["data"]["api_key"]["id"]
    revoked = await client.delete(f"/api/v1/api-keys/{key_id}", headers={"X-API-Key": plaintext})
    assert revoked.status_code == 204
    after_revocation = await client.get("/api/v1/users/me", headers={"X-API-Key": plaintext})
    assert after_revocation.status_code == 401


async def test_admin_can_manage_users_but_not_self_demote(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    admin = await login_admin(client, ctx)
    admin_headers = bearer(admin["access_token"])
    member = await register(client, email="member@example.com")

    listed = await client.get("/api/v1/admin/users", headers=admin_headers)
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 2

    promoted = await client.patch(
        f"/api/v1/admin/users/{member['user']['id']}",
        json={"plan": "pro", "daily_quota": 500},
        headers=admin_headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["data"]["user"]["plan"] == "pro"
    assert promoted.json()["data"]["user"]["daily_quota"] == 500

    self_demote = await client.patch(
        f"/api/v1/admin/users/{admin['user']['id']}",
        json={"role": "user"},
        headers=admin_headers,
    )
    assert self_demote.status_code == 403

    forbidden = await client.get("/api/v1/admin/users", headers=bearer(member["access_token"]))
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"


async def test_admin_grants_credits_with_reason(client: httpx.AsyncClient, ctx: AppContext) -> None:
    admin = await login_admin(client, ctx)
    admin_headers = bearer(admin["access_token"])
    member = await register(client, email="granted@example.com")
    user_id = member["user"]["id"]

    granted = await client.post(
        f"/api/v1/admin/users/{user_id}/credits",
        json={"amount": 50, "reason": "support goodwill"},
        headers=admin_headers,
    )
    assert granted.status_code == 201
    assert granted.json()["data"]["kind"] == "admin_adjust"

    wallet = await client.get("/api/v1/billing/wallet", headers=bearer(member["access_token"]))
    assert wallet.json()["data"]["balance"] == 50

    missing_reason = await client.post(
        f"/api/v1/admin/users/{user_id}/credits",
        json={"amount": 10, "reason": "   "},
        headers=admin_headers,
    )
    assert missing_reason.status_code == 422

    assert ADMIN_PASSWORD  # keep the credential constant obvious for the reader
