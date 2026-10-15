"""Service catalogue rules and the invocation state machine."""

from __future__ import annotations

import pytest

from tinysaas.domain.access.policy import AccessPolicy, Principal
from tinysaas.domain.catalog.service import ExecMode, Service, ServiceInactive
from tinysaas.domain.errors import Forbidden, ValidationError
from tinysaas.domain.identity.user import Role
from tinysaas.domain.invocation.invocation import Invocation, InvocationStatus


def make_service(**overrides: object) -> Service:
    values: dict[str, object] = {"slug": "Echo", "name": "Echo", "credit_cost": 2}
    values.update(overrides)
    return Service.create(**values)  # type: ignore[arg-type]


def test_create_normalizes_the_slug_and_defaults() -> None:
    service = make_service()

    assert service.slug == "echo"
    assert service.exec_mode is ExecMode.SYNC
    assert service.timeout_secs == 30
    assert service.is_active is True
    assert service.uses_upstream is False


@pytest.mark.parametrize(
    "slug", ["a", "with space", "-leading", "x" * 41, "trailing-", "double--ok?", "中文"]
)
def test_slug_validation(slug: str) -> None:
    with pytest.raises(ValidationError):
        make_service(slug=slug)


def test_slug_is_lowercased_and_may_contain_hyphens() -> None:
    assert make_service(slug="BG-Remove").slug == "bg-remove"
    assert make_service(slug="bg-remove").slug == "bg-remove"


@pytest.mark.parametrize(
    ("field", "value"),
    [("credit_cost", 0), ("credit_cost", -3), ("timeout_secs", 0), ("timeout_secs", 601)],
)
def test_numeric_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        make_service(**{field: value})


def test_upstream_url_must_be_http() -> None:
    with pytest.raises(ValidationError):
        make_service(upstream_url="grpc://worker:50051")
    service = make_service(upstream_url="http://worker:8000/predict")
    assert service.uses_upstream is True


def test_update_and_deactivate() -> None:
    service = make_service(upstream_url="http://worker:8000/run")

    service.update(credit_cost=5, is_active=False)
    assert service.credit_cost == 5
    assert service.is_active is False

    service.update(clear_upstream_url=True)
    assert service.upstream_url is None

    service.update(is_active=True)
    service.deactivate()
    assert service.is_active is False


def test_invocation_snapshots_the_price_and_settles_once() -> None:
    service = make_service(credit_cost=3)
    user_id = make_service_slug_user()

    invocation = Invocation.create_pending(
        user_id=user_id, service=service, request_id="req-1", idempotency_key="key-1"
    )
    assert invocation.status is InvocationStatus.PENDING
    assert invocation.credit_cost == 3

    invocation.mark_queued()
    assert invocation.status is InvocationStatus.QUEUED

    invocation.mark_running()
    invocation.record_response(body='{"ok":true}', content_type="application/json")
    invocation.mark_succeeded(latency_ms=12, upstream_status=200)

    assert invocation.status is InvocationStatus.SUCCEEDED
    assert invocation.credits_charged == 3
    assert invocation.credits_refunded == 0
    assert invocation.is_terminal is True

    with pytest.raises(ValidationError):
        invocation.mark_succeeded(latency_ms=1)
    with pytest.raises(ValidationError):
        invocation.record_response(body="x", content_type="text/plain")


def test_invocation_records_whether_the_refund_happened() -> None:
    service = make_service(credit_cost=2)
    user_id = make_service_slug_user()

    refunded = Invocation.create_pending(user_id=user_id, service=service, request_id="req-2")
    refunded.mark_failed(error_code="UPSTREAM_FAILED", error_message="boom", refunded=True)
    assert refunded.status is InvocationStatus.REFUNDED
    assert refunded.credits_refunded == 2
    assert refunded.credits_charged == 0

    broken = Invocation.create_pending(user_id=user_id, service=service, request_id="req-3")
    broken.mark_failed(error_code="UPSTREAM_FAILED", error_message="boom", refunded=False)
    assert broken.status is InvocationStatus.FAILED
    assert broken.credits_refunded == 0


def test_idempotency_key_bounds() -> None:
    service = make_service()
    with pytest.raises(ValidationError):
        Invocation.create_pending(
            user_id=make_service_slug_user(), service=service, request_id="r", idempotency_key=""
        )


def make_service_slug_user():  # type: ignore[no-untyped-def]
    from uuid import uuid4

    return uuid4()


def test_access_policy_matrix() -> None:
    from uuid import uuid4

    owner = uuid4()
    other = uuid4()
    member = Principal(user_id=owner, role=Role.USER, plan="free", daily_quota=20)  # type: ignore[arg-type]
    stranger = Principal(user_id=other, role=Role.USER, plan="free", daily_quota=20)  # type: ignore[arg-type]
    admin = Principal(user_id=other, role=Role.ADMIN, plan="pro", daily_quota=1000)  # type: ignore[arg-type]

    assert AccessPolicy.can_view_invocation(member, owner) is True
    assert AccessPolicy.can_view_invocation(stranger, owner) is False
    assert AccessPolicy.can_view_invocation(admin, owner) is True

    AccessPolicy.ensure_can_view_invocation(member, owner)
    with pytest.raises(Forbidden):
        AccessPolicy.ensure_can_view_invocation(stranger, owner)

    AccessPolicy.ensure_admin(admin)
    with pytest.raises(Forbidden):
        AccessPolicy.ensure_admin(member)

    inactive = make_service(is_active=False)
    with pytest.raises(ServiceInactive):
        AccessPolicy.ensure_can_invoke(member, inactive)
    AccessPolicy.ensure_can_invoke(member, make_service())
