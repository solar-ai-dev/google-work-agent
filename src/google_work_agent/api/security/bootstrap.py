"""Bootstrap grant storage for local session establishment."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, replace
from enum import StrEnum

BOOTSTRAP_TTL_MS = 60_000


def calculate_secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class BootstrapGrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class BootstrapGrantRecord:
    digest: str
    service_instance_id: str
    expires_at_ms: int
    status: BootstrapGrantStatus


@dataclass(frozen=True, slots=True)
class BootstrapConsumeResult:
    allowed: bool
    detail_code: str


class BootstrapGrantStore:
    """Consume one-time bootstrap grants without storing raw secrets."""

    def provision(self, *, secret: str, service_instance_id: str, now_ms: int) -> None:
        raise NotImplementedError

    def consume(
        self,
        *,
        secret: str,
        service_instance_id: str,
        now_ms: int,
    ) -> BootstrapConsumeResult:
        raise NotImplementedError


class InMemoryBootstrapGrantStore(BootstrapGrantStore):
    def __init__(self, *, ttl_ms: int = BOOTSTRAP_TTL_MS) -> None:
        self._ttl_ms = ttl_ms
        self._records: dict[str, BootstrapGrantRecord] = {}

    def provision(self, *, secret: str, service_instance_id: str, now_ms: int) -> None:
        digest = calculate_secret_digest(secret)
        self._records[digest] = BootstrapGrantRecord(
            digest=digest,
            service_instance_id=service_instance_id,
            expires_at_ms=now_ms + self._ttl_ms,
            status=BootstrapGrantStatus.ACTIVE,
        )

    def consume(
        self,
        *,
        secret: str,
        service_instance_id: str,
        now_ms: int,
    ) -> BootstrapConsumeResult:
        digest = calculate_secret_digest(secret)
        record = self._find_record(digest)
        if record is None:
            return BootstrapConsumeResult(allowed=False, detail_code="BOOTSTRAP_SECRET_INVALID")
        if record.expires_at_ms < now_ms:
            self._records[record.digest] = replace(record, status=BootstrapGrantStatus.EXPIRED)
            return BootstrapConsumeResult(allowed=False, detail_code="BOOTSTRAP_SECRET_EXPIRED")
        if record.status is BootstrapGrantStatus.CONSUMED:
            return BootstrapConsumeResult(allowed=False, detail_code="BOOTSTRAP_SECRET_CONSUMED")
        if record.service_instance_id != service_instance_id:
            return BootstrapConsumeResult(
                allowed=False,
                detail_code="BOOTSTRAP_SERVICE_INSTANCE_MISMATCH",
            )
        self._records[record.digest] = replace(record, status=BootstrapGrantStatus.CONSUMED)
        return BootstrapConsumeResult(allowed=True, detail_code="BOOTSTRAP_CONSUMED")

    def _find_record(self, digest: str) -> BootstrapGrantRecord | None:
        for stored_digest, record in self._records.items():
            if hmac.compare_digest(stored_digest, digest):
                return record
        return None
