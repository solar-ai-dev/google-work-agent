"""Replaceable OS secret-store boundary."""

from typing import Protocol


class SecretStorePort(Protocol):
    def put(self, key: str, secret_bytes: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...


__all__ = ["SecretStorePort"]
