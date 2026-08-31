"""Local session issuance and validation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass


def calculate_session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LocalSessionRecord:
    digest: str
    service_instance_id: str
    created_at_ms: int
    expires_at_ms: int | None
    compatible: bool


class LocalSessionManager:
    """Issue and validate in-memory local sessions."""

    def issue(self, *, service_instance_id: str, now_ms: int, compatible: bool) -> str:
        raise NotImplementedError

    def resolve(
        self,
        *,
        token: str | None,
        service_instance_id: str,
        now_ms: int,
    ) -> LocalSessionRecord | None:
        raise NotImplementedError

    def invalidate_all(self) -> None:
        raise NotImplementedError


class InMemoryLocalSessionManager(LocalSessionManager):
    def __init__(self, *, ttl_ms: int | None = None) -> None:
        if ttl_ms is not None and ttl_ms <= 0:
            raise ValueError("ttl_ms must be positive when configured")
        self._ttl_ms = ttl_ms
        self._records: dict[str, LocalSessionRecord] = {}
        self._lock = threading.Lock()

    def issue(self, *, service_instance_id: str, now_ms: int, compatible: bool = True) -> str:
        token = secrets.token_urlsafe(32)
        digest = calculate_session_digest(token)
        with self._lock:
            self._records[digest] = LocalSessionRecord(
                digest=digest,
                service_instance_id=service_instance_id,
                created_at_ms=now_ms,
                expires_at_ms=None if self._ttl_ms is None else now_ms + self._ttl_ms,
                compatible=compatible,
            )
        return token

    def resolve(
        self,
        *,
        token: str | None,
        service_instance_id: str,
        now_ms: int,
    ) -> LocalSessionRecord | None:
        if token is None:
            return None
        digest = calculate_session_digest(token)
        with self._lock:
            for stored_digest, record in self._records.items():
                if not hmac.compare_digest(stored_digest, digest):
                    continue
                if record.service_instance_id != service_instance_id:
                    return None
                if record.expires_at_ms is not None and now_ms > record.expires_at_ms:
                    self._records.pop(stored_digest, None)
                    return None
                return record
        return None

    def invalidate_all(self) -> None:
        with self._lock:
            self._records.clear()
