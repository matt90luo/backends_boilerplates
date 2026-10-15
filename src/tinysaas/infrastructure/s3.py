"""S3 compatible object storage client (boto3, executed off the event loop)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

from tinysaas.infrastructure.config import Settings


@dataclass(slots=True)
class S3Storage:
    """Thin wrapper around the boto3 client plus the public endpoint mapping."""

    client: Any
    bucket: str
    endpoint_url: str
    public_endpoint_url: str | None
    presign_ttl_seconds: int

    def rewrite_host(self, url: str) -> str:
        """Swap the internal endpoint for the browser reachable one."""
        if not self.public_endpoint_url:
            return url
        return url.replace(self.endpoint_url.rstrip("/"), self.public_endpoint_url.rstrip("/"), 1)

    async def ping(self) -> None:
        import asyncio

        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    async def ensure_bucket(self) -> None:
        """Create the bucket when missing (handy for local RustFS/MinIO)."""
        import asyncio

        def _run() -> None:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except Exception:
                self.client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(_run)


def create_s3_storage(settings: Settings) -> S3Storage:
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    return S3Storage(
        client=client,
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        public_endpoint_url=settings.s3_public_endpoint_url,
        presign_ttl_seconds=settings.presign_ttl_seconds,
    )
