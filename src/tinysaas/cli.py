"""Operational CLI: seeding, admin creation and schema helpers.

Usage::

    uv run python -m tinysaas.cli seed
    uv run python -m tinysaas.cli create-admin --email admin@example.com --password secret123
    uv run python -m tinysaas.cli create-tables
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from tinysaas.adapters.persistence.models import Base
from tinysaas.adapters.persistence.schema import create_all, drop_all
from tinysaas.application.errors import EmailAlreadyRegistered
from tinysaas.application.ports.persistence import UnitOfWork
from tinysaas.containers.container import Container, build_container, stop_resources
from tinysaas.domain.billing.credits import CreditAmount
from tinysaas.domain.billing.package import CreditPackage
from tinysaas.domain.billing.wallet import Wallet
from tinysaas.domain.catalog.service import ExecMode, Service
from tinysaas.domain.identity.password import validate_password
from tinysaas.domain.identity.user import Plan, Role, User, normalize_email

DEMO_PACKAGES = (
    ("starter", "Starter", 100, 500, "usd", "stripe_price_starter"),
    ("pro", "Pro", 500, 2000, "usd", "stripe_price_pro"),
    ("scale", "Scale", 2000, 7000, "usd", "stripe_price_scale"),
)


@dataclass(frozen=True, slots=True)
class DemoService:
    slug: str
    name: str
    description: str
    credit_cost: int
    exec_mode: ExecMode


DEMO_SERVICES: tuple[DemoService, ...] = (
    DemoService(
        slug="echo",
        name="Echo",
        description="内置演示服务：原样返回请求体，用于验证扣费闭环。",
        credit_cost=1,
        exec_mode=ExecMode.SYNC,
    ),
    DemoService(
        slug="slow-report",
        name="Slow report",
        description="内置异步演示服务：模拟耗时 2 秒的报表任务。",
        credit_cost=3,
        exec_mode=ExecMode.ASYNC,
    ),
    DemoService(
        slug="always-fails",
        name="Always fails",
        description="内置演示服务：必定失败，用于验证 credit 回滚。",
        credit_cost=1,
        exec_mode=ExecMode.SYNC,
    ),
)


async def _ensure_admin(
    uow: UnitOfWork, container: Container, *, email: str, password: str, initial_credits: int
) -> User:
    normalized = normalize_email(email)
    existing = await uow.users.get_by_email(normalized)
    if existing is not None:
        return existing
    validate_password(password)
    now = datetime.now(UTC)
    user = User.register(
        email=normalized,
        password_hash=container.password_hasher().hash(password),
        role=Role.ADMIN,
        plan=Plan.PRO,
        now=now,
    )
    await uow.users.add(user)
    wallet = Wallet.for_user(user.id, now=now)
    await uow.wallets.add(wallet)
    if initial_credits > 0:
        entry = wallet.top_up(CreditAmount(initial_credits), reference="seed:admin", now=now)
        await uow.wallets.update(wallet)
        await uow.ledger.add(entry)
    return user


async def _seed_packages(uow: UnitOfWork, container: Container) -> int:
    settings = container.settings()
    prices = {
        "stripe_price_starter": settings.stripe_price_starter,
        "stripe_price_pro": settings.stripe_price_pro,
        "stripe_price_scale": settings.stripe_price_scale,
    }
    created = 0
    for slug, name, credits, amount_minor, currency, price_attr in DEMO_PACKAGES:
        if await uow.packages.get_by_slug(slug) is not None:
            continue
        await uow.packages.add(
            CreditPackage(
                id=uuid4(),
                slug=slug,
                name=name,
                credits=credits,
                amount_minor=amount_minor,
                currency=currency,
                stripe_price_id=prices[price_attr],
            )
        )
        created += 1
    return created


async def _seed_services(uow: UnitOfWork) -> int:
    created = 0
    for spec in DEMO_SERVICES:
        if await uow.services.get_by_slug(spec.slug) is not None:
            continue
        service = Service.create(
            slug=spec.slug,
            name=spec.name,
            description=spec.description,
            credit_cost=spec.credit_cost,
            exec_mode=spec.exec_mode,
        )
        await uow.services.add(service)
        created += 1
    return created


async def _seed(container: Container) -> None:
    settings = container.settings()
    uow_factory = container.uow_factory()
    async with uow_factory() as uow:
        admin = await _ensure_admin(
            uow,
            container,
            email=settings.admin_email,
            password=settings.admin_password,
            initial_credits=10_000,
        )
        packages = await _seed_packages(uow, container)
        services = await _seed_services(uow)
        await uow.commit()
    print(f"seeded: admin={admin.email} packages+{packages} services+{services}")


async def _create_admin(container: Container, email: str, password: str) -> None:
    uow_factory = container.uow_factory()
    async with uow_factory() as uow:
        user = await _ensure_admin(
            uow, container, email=email, password=password, initial_credits=0
        )
        await uow.commit()
    print(f"admin ready: {user.email} ({user.id})")


async def _create_tables(container: Container) -> None:
    resources = container.resources()
    await create_all(resources.postgres.engine)
    print(f"created {len(Base.metadata.tables)} tables")


async def _drop_tables(container: Container) -> None:
    resources = container.resources()
    await drop_all(resources.postgres.engine)
    print("dropped all tables")


async def _main(args: argparse.Namespace) -> None:
    container = build_container()
    try:
        if args.command == "seed":
            await _seed(container)
        elif args.command == "create-admin":
            await _create_admin(container, args.email, args.password)
        elif args.command == "create-tables":
            await _create_tables(container)
        elif args.command == "drop-tables":
            await _drop_tables(container)
        else:  # pragma: no cover - argparse guards this
            raise SystemExit(f"unknown command: {args.command}")
    finally:
        await stop_resources(container)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinysaas", description="Tiny SaaS CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="create the admin user, demo packages and demo services")
    admin = sub.add_parser("create-admin", help="create or confirm an administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", required=True)
    sub.add_parser("create-tables", help="create all tables from the ORM metadata")
    sub.add_parser("drop-tables", help="drop all tables (destructive)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(_main(args))
    except EmailAlreadyRegistered as error:  # pragma: no cover - message only
        print(f"error: {error.message}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
