"""S3/RustFS presigned URL adapter (boto3 executed in a thread)."""

from __future__ import annotations

import asyncio

from tinysaas.infrastructure.s3 import S3Storage


class S3ObjectStorage:
    """Adapter implementing :class:`ObjectStorage`."""

    def __init__(self, storage: S3Storage) -> None:
        self._storage = storage

    async def presign_put(self, *, key: str, content_type: str, expires_in: int) -> str:
        url = await asyncio.to_thread(
            self._storage.client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._storage.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return self._storage.rewrite_host(str(url))

    async def presign_get(
        self, *, key: str, expires_in: int, download_name: str | None = None
    ) -> str:
        params: dict[str, str] = {"Bucket": self._storage.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        url = await asyncio.to_thread(
            self._storage.client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return self._storage.rewrite_host(str(url))

    async def exists(self, *, key: str) -> bool:
        def _head() -> bool:
            try:
                self._storage.client.head_object(Bucket=self._storage.bucket, Key=key)
            except Exception:
                return False
            return True

        return await asyncio.to_thread(_head)
