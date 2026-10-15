"""Jinja2 template rendering for transactional emails."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateNotFound,
    select_autoescape,
)

from tinysaas.domain.errors import DomainError

DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"


class TemplateNotFoundError(DomainError):
    code = "EMAIL_TEMPLATE_MISSING"


class TemplateRenderer:
    """Renders ``<template>.html`` with the given context."""

    def __init__(self, *, template_dir: Path | None = None) -> None:
        self._environment = Environment(
            loader=FileSystemLoader(str(template_dir or DEFAULT_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template: str, context: Mapping[str, object]) -> str:
        try:
            return self._environment.get_template(f"{template}.html").render(**context)
        except TemplateNotFound as error:
            raise TemplateNotFoundError(f"邮件模板不存在: {template}") from error
