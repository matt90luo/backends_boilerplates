"""Presigned upload / download use cases (S3 compatible storage)."""

from __future__ import annotations

from uuid import uuid4

from tinysaas.application.dto.commands import PresignDownloadQuery, PresignUploadCommand
from tinysaas.application.dto.files import PresignedDownloadView, PresignedUploadView
from tinysaas.application.options import AppOptions
from tinysaas.application.ports.external import ObjectStorage
from tinysaas.domain.access.policy import Principal
from tinysaas.domain.errors import Forbidden, ValidationError

_PURPOSES = ("avatar", "artifact")

_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/json": ".json",
    "text/csv": ".csv",
    "application/zip": ".zip",
    "text/plain": ".txt",
}


class PresignUploadUseCase:
    """Hand the client a URL so bytes never flow through this service."""

    def __init__(self, *, storage: ObjectStorage, options: AppOptions) -> None:
        self._storage = storage
        self._options = options

    async def execute(
        self, principal: Principal, command: PresignUploadCommand
    ) -> PresignedUploadView:
        options = self._options.upload
        if command.purpose not in _PURPOSES:
            raise ValidationError(
                f"purpose 必须是 {'/'.join(_PURPOSES)}", details={"field": "purpose"}
            )
        if command.content_type not in options.allowed_content_types:
            raise ValidationError(
                "不支持的文件类型",
                details={
                    "field": "content_type",
                    "allowed": list(options.allowed_content_types),
                },
            )
        if command.size <= 0 or command.size > options.max_upload_bytes:
            raise ValidationError(
                f"文件大小必须在 1 到 {options.max_upload_bytes} 字节之间",
                details={"field": "size"},
            )
        extension = _EXTENSIONS.get(command.content_type, "")
        key = f"users/{principal.user_id}/{command.purpose}/{uuid4().hex}{extension}"
        url = await self._storage.presign_put(
            key=key, content_type=command.content_type, expires_in=options.presign_ttl_seconds
        )
        return PresignedUploadView(
            key=key,
            url=url,
            expires_in=options.presign_ttl_seconds,
            max_bytes=options.max_upload_bytes,
            content_type=command.content_type,
        )


class PresignDownloadUseCase:
    def __init__(self, *, storage: ObjectStorage, options: AppOptions) -> None:
        self._storage = storage
        self._options = options

    async def execute(
        self, principal: Principal, query: PresignDownloadQuery
    ) -> PresignedDownloadView:
        self._ensure_owner(principal, query.key)
        options = self._options.upload
        url = await self._storage.presign_get(
            key=query.key,
            expires_in=options.presign_ttl_seconds,
            download_name=query.download_name,
        )
        return PresignedDownloadView(key=query.key, url=url, expires_in=options.presign_ttl_seconds)

    def _ensure_owner(self, principal: Principal, key: str) -> None:
        if key.startswith(f"users/{principal.user_id}/"):
            return
        if principal.is_admin and self._options.upload.allow_artifact_download_for_admin:
            return
        raise Forbidden("无权访问该文件")
