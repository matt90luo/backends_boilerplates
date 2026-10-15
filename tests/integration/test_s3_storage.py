"""Integration test for presigned uploads against the local S3 (RustFS)."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tinysaas.adapters.storage.s3_storage import S3ObjectStorage
from tinysaas.infrastructure.config import get_settings
from tinysaas.infrastructure.s3 import create_s3_storage

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_presigned_put_and_get_round_trip() -> None:
    settings = get_settings()
    storage = S3ObjectStorage(create_s3_storage(settings))
    await create_s3_storage(settings).ensure_bucket()
    key = f"users/it-{uuid4().hex}/artifact/payload.txt"

    put_url = await storage.presign_put(key=key, content_type="text/plain", expires_in=300)
    async with httpx.AsyncClient() as client:
        uploaded = await client.put(
            put_url, content=b"hello rustfs", headers={"Content-Type": "text/plain"}
        )
        assert uploaded.status_code in {200, 204}, uploaded.text

        get_url = await storage.presign_get(key=key, expires_in=300)
        downloaded = await client.get(get_url)

    assert downloaded.status_code == 200
    assert downloaded.content == b"hello rustfs"
    assert await storage.exists(key=key) is True


async def test_presigned_urls_use_the_public_endpoint_when_configured() -> None:
    settings = get_settings()
    settings.s3_public_endpoint_url = "https://cdn.example.com"
    storage = S3ObjectStorage(create_s3_storage(settings))

    url = await storage.presign_put(
        key="users/x/artifact/a.png", content_type="image/png", expires_in=60
    )

    assert url.startswith("https://cdn.example.com/")
