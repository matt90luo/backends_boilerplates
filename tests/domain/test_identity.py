"""User, password and session invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tinysaas.domain.errors import Forbidden, ValidationError
from tinysaas.domain.identity.password import WeakPassword, validate_password
from tinysaas.domain.identity.session import RefreshToken
from tinysaas.domain.identity.user import Plan, Role, User, normalize_email


def make_user(**overrides: object) -> User:
    values: dict[str, object] = {
        "email": "Person@Example.COM",
        "password_hash": "hashed",
    }
    values.update(overrides)
    return User.register(**values)  # type: ignore[arg-type]


def test_register_normalizes_email_and_applies_plan_quota() -> None:
    user = make_user(plan=Plan.PRO)

    assert user.email == "person@example.com"
    assert user.role is Role.USER
    assert user.daily_quota == 1000
    assert user.is_active is True
    assert user.is_email_verified is False


@pytest.mark.parametrize(
    "email", ["no-at-sign", "a@b", "two@@example.com", "  ", "a b@example.com"]
)
def test_register_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        normalize_email(email)


def test_daily_quota_must_be_within_bounds() -> None:
    with pytest.raises(ValidationError):
        make_user(daily_quota=-1)


def test_admin_cannot_change_own_role_or_disable_self() -> None:
    admin = make_user(role=Role.ADMIN)
    with pytest.raises(Forbidden):
        admin.apply_admin_update(actor_id=admin.id, role=Role.USER)
    with pytest.raises(Forbidden):
        admin.apply_admin_update(actor_id=admin.id, is_active=False)


def test_admin_update_can_change_plan_and_quota() -> None:
    user = make_user()
    admin_id = make_user(role=Role.ADMIN).id

    user.apply_admin_update(actor_id=admin_id, plan=Plan.PRO)

    assert user.plan is Plan.PRO
    assert user.daily_quota == 1000

    user.apply_admin_update(actor_id=admin_id, daily_quota=5, is_active=False)
    assert user.daily_quota == 5
    assert user.is_active is False


def test_mark_email_verified_is_idempotent() -> None:
    user = make_user()
    first = datetime(2026, 1, 1, tzinfo=UTC)
    user.mark_email_verified(now=first)
    user.mark_email_verified(now=first + timedelta(days=1))

    assert user.email_verified_at == first


@pytest.mark.parametrize("password", ["short1", "allletters", "12345678", " spaces 1 "])
def test_password_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(WeakPassword):
        validate_password(password)


def test_password_policy_accepts_mixed_password() -> None:
    validate_password("Passw0rd!23")


def test_refresh_token_rotation_and_revocation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    token = RefreshToken.issue(
        user_id=make_user().id,
        token_hash="digest",
        ttl=timedelta(days=30),
        now=now,
    )

    assert token.is_active(now=now) is True
    token.rotate(now=now)
    assert token.is_active(now=now) is False
    with pytest.raises(ValidationError):
        token.rotate(now=now)

    fresh = RefreshToken.issue(
        user_id=make_user().id, token_hash="digest2", ttl=timedelta(days=30), now=now
    )
    fresh.revoke(now=now)
    assert fresh.is_revoked is True
    assert fresh.is_active(now=now) is False


def test_refresh_token_expiry() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    token = RefreshToken.issue(
        user_id=make_user().id, token_hash="digest", ttl=timedelta(minutes=5), now=now
    )
    assert token.is_active(now=now + timedelta(minutes=6)) is False
