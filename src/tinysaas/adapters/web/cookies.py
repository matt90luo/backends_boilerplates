"""Refresh token cookie policy (body mode by default, cookie mode optional)."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.responses import Response

from tinysaas.infrastructure.config import Settings


@dataclass(frozen=True, slots=True)
class CookiePolicy:
    enabled: bool
    name: str
    secure: bool
    path: str

    def set(self, response: Response, token: str, *, max_age: int) -> None:
        if not self.enabled:
            return
        response.set_cookie(
            self.name,
            token,
            max_age=max_age,
            httponly=True,
            secure=self.secure,
            samesite="lax",
            path=self.path,
        )

    def clear(self, response: Response) -> None:
        if not self.enabled:
            return
        response.delete_cookie(self.name, path=self.path)


def build_cookie_policy(settings: Settings) -> CookiePolicy:
    return CookiePolicy(
        enabled=settings.refresh_transport == "cookie",
        name=settings.refresh_cookie_name,
        secure=settings.refresh_cookie_secure,
        path=settings.refresh_cookie_path,
    )
