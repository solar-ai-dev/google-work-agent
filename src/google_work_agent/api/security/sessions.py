"""Local session issuance and validation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


def calculate_session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LocalSessionRecord:
    digest: str
    service_instance_id: str
    created_at_ms: int


class LocalSessionManager:
    """Issue and validate in-memory local sessions."""

    def issue(self, *, service_instance_id: str, now_ms: int) -> str:
        raise NotImplementedError

    def validate(self, *, token: str | None, service_instance_id: str) -> bool:
        raise NotImplementedError


class InMemoryLocalSessionManager(LocalSessionManager):
    def __init__(self) -> None:
        self._records: dict[str, LocalSessionRecord] = {}

    def issue(self, *, service_instance_id: str, now_ms: int) -> str:
        token = secrets.token_urlsafe(32)
        digest = calculate_session_digest(token)
        self._records[digest] = LocalSessionRecord(
            digest=digest,
            service_instance_id=service_instance_id,
            created_at_ms=now_ms,
        )
        return token

    def validate(self, *, token: str | None, service_instance_id: str) -> bool:
        if token is None:
            return False
        digest = calculate_session_digest(token)
        for stored_digest, record in self._records.items():
            if hmac.compare_digest(stored_digest, digest):
                return record.service_instance_id == service_instance_id
        return False
