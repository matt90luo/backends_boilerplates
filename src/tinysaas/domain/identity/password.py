"""Password policy."""

from __future__ import annotations

from tinysaas.domain.errors import ValidationError

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class WeakPassword(ValidationError):
    code = "WEAK_PASSWORD"


def validate_password(password: str) -> None:
    """Raise :class:`WeakPassword` when *password* does not satisfy the policy."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise WeakPassword(f"密码长度至少 {PASSWORD_MIN_LENGTH} 位", details={"field": "password"})
    if len(password) > PASSWORD_MAX_LENGTH:
        raise WeakPassword(
            f"密码长度不能超过 {PASSWORD_MAX_LENGTH} 位", details={"field": "password"}
        )
    if password.strip() != password:
        raise WeakPassword("密码首尾不能包含空白字符", details={"field": "password"})
    if password.isdigit() or password.isalpha():
        raise WeakPassword("密码需要同时包含字母和数字", details={"field": "password"})
