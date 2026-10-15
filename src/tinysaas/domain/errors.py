"""Domain level errors.

Errors carry a stable ``code`` so the web layer can translate them into the
standard error envelope without the domain knowing anything about HTTP.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every business rule violation."""

    code = "DOMAIN_ERROR"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = dict(details or {})


class ValidationError(DomainError):
    """Input violates a domain invariant."""

    code = "VALIDATION_ERROR"


class Forbidden(DomainError):
    """The acting principal is not allowed to perform the action."""

    code = "FORBIDDEN"


class NotFound(DomainError):
    """The requested aggregate does not exist."""

    code = "NOT_FOUND"


class Conflict(DomainError):
    """The requested change collides with the current state."""

    code = "CONFLICT"
