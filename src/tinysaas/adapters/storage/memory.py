"""In-memory storage double: used by tests and for local demos without S3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from tinysaas.application.errors import StorageError


class InMemoryObjectStorage:
    def __init__(self, *, base_url: str = "http://storage.local") -> None:
        self._base_url = base_url.rstrip("/")
        self._objects: dict[str, bytes] = {}
        self._keys: set[str] = set()

    async def presign_put(self, *, key: str, content_type: str, expires_in: int) -> str:
        self._keys.add(key)
        return self._url("put", key, expires_in, content_type=content_type)

    async def presign_get(
        self, *, key: str, expires_in: int, download_name: str | None = None
    ) -> str:
        self._keys.add(key)
        return self._url("get", key, expires_in, download_name=download_name)

    async def exists(self, *, key: str) -> bool:
        return key in self._objects

    def put_object(self, *, key: str, body: bytes) -> None:
        """Test helper simulating the client's direct upload."""
        self._objects[key] = body

    def _url(self, verb: str, key: str, expires_in: int, **extra: object) -> str:
        if not key or key.startswith("/"):
            raise StorageError("非法的对象 key")
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        query = {"verb": verb, "expires": expires_at.isoformat()}
        query.update({k: str(v) for k, v in extra.items() if v is not None})
        return f"{self._base_url}/{key}?{urlencode(query)}"
