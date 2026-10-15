"""Administration DTOs."""

from __future__ import annotations

from dataclasses import dataclass

from tinysaas.application.dto.identity import UserView


@dataclass(frozen=True, slots=True)
class AdminUserView:
    """A user plus wallet state, only visible to administrators."""

    user: UserView
    balance: int
    reserved: int
