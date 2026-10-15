"""File transfer DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PresignedUploadView:
    key: str
    url: str
    expires_in: int
    max_bytes: int
    content_type: str


@dataclass(frozen=True, slots=True)
class PresignedDownloadView:
    key: str
    url: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: str
    components: dict[str, str]
