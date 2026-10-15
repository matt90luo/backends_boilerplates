"""API key generation and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from tinysaas.application.ports.security import ApiKeyMaterial

_PREFIX_BYTES = 4
_SECRET_BYTES = 32
_PARTS = 3


class HashedApiKeyService:
    """Format: ``<prefix>_<lookup>_<secret>``.

    The lookup part is stored in clear so authentication is a single indexed
    read followed by a constant time comparison of the secret digest.
    """

    def __init__(self, *, prefix: str = "tsk", salt: str = "") -> None:
        self._prefix = prefix or "tsk"
        self._salt = salt

    def generate(self) -> ApiKeyMaterial:
        lookup = secrets.token_hex(_PREFIX_BYTES)
        secret = secrets.token_urlsafe(_SECRET_BYTES)
        plaintext = f"{self._prefix}_{lookup}_{secret}"
        return ApiKeyMaterial(plaintext=plaintext, prefix=lookup, key_hash=self.hash(plaintext))

    def hash(self, plaintext: str) -> str:
        return hashlib.sha256(f"{self._salt}{plaintext}".encode()).hexdigest()

    def prefix_of(self, plaintext: str) -> str:
        parts = plaintext.split("_")
        if len(parts) != _PARTS:
            return ""
        return parts[1]

    def verify(self, key_hash: str, plaintext: str) -> bool:
        return hmac.compare_digest(key_hash, self.hash(plaintext))
