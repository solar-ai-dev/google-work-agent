"""Issue opaque authenticated resource-selection handles."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps
from typing import Literal


@dataclass(frozen=True, slots=True)
class ResourceSelectionHandlePayloadV1:
    schema_version: Literal[1]
    service_instance_id: str
    session_digest: str
    account_id: str
    connector_id: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
    version_token: str | None
    issued_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class IssueSelectionHandleCommand:
    session_digest: str
    account_id: str
    connector_id: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
    version_token: str | None


class IssueSelectionHandle:
    def __init__(
        self,
        *,
        signing_secret: bytes,
        service_instance_id: str,
        now_ms: Callable[[], int],
        ttl_ms: int,
    ) -> None:
        if len(signing_secret) < 32:
            raise ValueError("selection-handle signing secret must be at least 256 bits")
        if not service_instance_id or ttl_ms < 1:
            raise ValueError("invalid selection-handle issuer configuration")
        self._secret = signing_secret
        self._service_instance_id = service_instance_id
        self._now_ms = now_ms
        self._ttl_ms = ttl_ms

    def __call__(self, command: IssueSelectionHandleCommand) -> str:
        _require_digest(command.session_digest)
        for value in (
            command.account_id,
            command.connector_id,
            command.resource_type,
            command.resource_id,
        ):
            if not value:
                raise ValueError("selection-handle identity fields must be non-empty")
        issued_at_ms = self._now_ms()
        payload = ResourceSelectionHandlePayloadV1(
            schema_version=1,
            service_instance_id=self._service_instance_id,
            session_digest=command.session_digest,
            account_id=command.account_id,
            connector_id=command.connector_id,
            resource_type=command.resource_type,
            resource_id=command.resource_id,
            parent_resource_id=command.parent_resource_id,
            version_token=command.version_token,
            issued_at_ms=issued_at_ms,
            expires_at_ms=issued_at_ms + self._ttl_ms,
        )
        encoded_payload = _base64url(
            dumps(asdict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _base64url(
            hmac.new(self._secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"v1.{encoded_payload}.{signature}"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("session_digest must be a lowercase SHA-256 value")
