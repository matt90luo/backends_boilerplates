"""Service catalog aggregate: the tool registry exposed by the gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from tinysaas.domain.errors import DomainError, ValidationError

# 2-40 chars, lowercase letters/digits/hyphens, no leading or trailing hyphen
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
_MAX_CREDIT_COST = 100_000
_MAX_TIMEOUT_SECONDS = 600
_SERVICE_NAME_MAX_LENGTH = 80
_UPSTREAM_URL_MAX_LENGTH = 500


class ExecMode(StrEnum):
    """How the gateway dispatches a call."""

    SYNC = "sync"
    ASYNC = "async"


class ServiceInactive(DomainError):
    code = "SERVICE_INACTIVE"


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_slug(slug: str) -> str:
    candidate = slug.strip().lower()
    if not _SLUG_RE.match(candidate):
        raise ValidationError(
            "slug 只能包含小写字母、数字和连字符，长度 2-40", details={"field": "slug"}
        )
    return candidate


@dataclass
class Service:
    """Metadata that drives the virtual dispatcher: price, mode, upstream."""

    id: UUID
    slug: str
    name: str
    credit_cost: int
    exec_mode: ExecMode = ExecMode.SYNC
    description: str | None = None
    upstream_url: str | None = None
    timeout_secs: int = 30
    is_active: bool = True
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def create(
        cls,
        *,
        slug: str,
        name: str,
        credit_cost: int,
        exec_mode: ExecMode = ExecMode.SYNC,
        description: str | None = None,
        upstream_url: str | None = None,
        timeout_secs: int = 30,
        is_active: bool = True,
        now: datetime | None = None,
    ) -> Service:
        moment = now or _now()
        return cls(
            id=uuid4(),
            slug=normalize_slug(slug),
            name=cls._validate_name(name),
            description=cls._clean_description(description),
            credit_cost=cls._validate_credit_cost(credit_cost),
            exec_mode=exec_mode,
            upstream_url=cls._validate_upstream_url(upstream_url),
            timeout_secs=cls._validate_timeout(timeout_secs),
            is_active=is_active,
            created_at=moment,
            updated_at=moment,
        )

    def update(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        credit_cost: int | None = None,
        exec_mode: ExecMode | None = None,
        upstream_url: str | None = None,
        clear_upstream_url: bool = False,
        timeout_secs: int | None = None,
        is_active: bool | None = None,
        now: datetime | None = None,
    ) -> None:
        if name is not None:
            self.name = self._validate_name(name)
        if description is not None:
            self.description = self._clean_description(description)
        if credit_cost is not None:
            self.credit_cost = self._validate_credit_cost(credit_cost)
        if exec_mode is not None:
            self.exec_mode = exec_mode
        if clear_upstream_url:
            self.upstream_url = None
        elif upstream_url is not None:
            self.upstream_url = self._validate_upstream_url(upstream_url)
        if timeout_secs is not None:
            self.timeout_secs = self._validate_timeout(timeout_secs)
        if is_active is not None:
            self.is_active = is_active
        self.updated_at = now or _now()

    def deactivate(self, *, now: datetime | None = None) -> None:
        self.is_active = False
        self.updated_at = now or _now()

    @property
    def uses_upstream(self) -> bool:
        return self.upstream_url is not None

    @staticmethod
    def _validate_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("服务名称不能为空", details={"field": "name"})
        if len(cleaned) > _SERVICE_NAME_MAX_LENGTH:
            raise ValidationError(
                f"服务名称不能超过 {_SERVICE_NAME_MAX_LENGTH} 个字符", details={"field": "name"}
            )
        return cleaned

    @staticmethod
    def _clean_description(description: str | None) -> str | None:
        if description is None:
            return None
        cleaned = description.strip()
        if len(cleaned) > 500:
            raise ValidationError("服务描述不能超过 500 个字符", details={"field": "description"})
        return cleaned or None

    @staticmethod
    def _validate_credit_cost(credit_cost: int) -> int:
        if credit_cost <= 0 or credit_cost > _MAX_CREDIT_COST:
            raise ValidationError(
                f"credit_cost 必须在 1 到 {_MAX_CREDIT_COST} 之间",
                details={"field": "credit_cost"},
            )
        return credit_cost

    @staticmethod
    def _validate_timeout(timeout_secs: int) -> int:
        if timeout_secs <= 0 or timeout_secs > _MAX_TIMEOUT_SECONDS:
            raise ValidationError(
                f"timeout_secs 必须在 1 到 {_MAX_TIMEOUT_SECONDS} 之间",
                details={"field": "timeout_secs"},
            )
        return timeout_secs

    @staticmethod
    def _validate_upstream_url(upstream_url: str | None) -> str | None:
        if upstream_url is None:
            return None
        cleaned = upstream_url.strip()
        if not cleaned:
            return None
        if not cleaned.startswith(("http://", "https://")):
            raise ValidationError(
                "upstream_url 必须是以 http:// 或 https:// 开头的地址",
                details={"field": "upstream_url"},
            )
        if len(cleaned) > _UPSTREAM_URL_MAX_LENGTH:
            raise ValidationError("upstream_url 过长", details={"field": "upstream_url"})
        return cleaned
