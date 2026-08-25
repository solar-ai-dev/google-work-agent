"""Fail-closed validation of opaque resource-selection handles."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError, loads
from typing import cast

from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    ResourceSelectionHandlePayloadV1,
    _require_digest,
)


class SelectionHandleValidationError(ValueError):
    """The authenticated selection identity is invalid for the current request."""


@dataclass(frozen=True, slots=True)
class ResolveSelectionHandleQuery:
    selection_handle: str
    session_digest: str
    account_id: str
    expected_connector_id: str | None = None
    expected_resource_type: str | None = None
    expected_resource_id: str | None = None
    expected_parent_resource_id: str | None = None
    require_parent_match: bool = False


class ResolveSelectionHandle:
    _PAYLOAD_FIELDS = {
        "schema_version",
        "service_instance_id",
        "session_digest",
        "account_id",
        "connector_id",
        "resource_type",
        "resource_id",
        "parent_resource_id",
        "version_token",
        "issued_at_ms",
        "expires_at_ms",
    }

    def __init__(
        self,
        *,
        signing_secret: bytes,
        service_instance_id: str,
        now_ms: Callable[[], int],
    ) -> None:
        if len(signing_secret) < 32 or not service_instance_id:
            raise ValueError("invalid selection-handle resolver configuration")
        self._secret = signing_secret
        self._service_instance_id = service_instance_id
        self._now_ms = now_ms

    def __call__(self, query: ResolveSelectionHandleQuery) -> ResourceSelectionHandlePayloadV1:
        try:
            _require_digest(query.session_digest)
            version, encoded_payload, encoded_signature = query.selection_handle.split(".")
            if version != "v1":
                raise ValueError("unsupported handle version")
            expected_signature = hmac.new(
                self._secret, encoded_payload.encode("ascii"), hashlib.sha256
            ).digest()
            signature = _decode_base64url(encoded_signature)
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("invalid handle signature")
            raw = loads(_decode_base64url(encoded_payload))
            if not isinstance(raw, dict) or set(raw) != self._PAYLOAD_FIELDS:
                raise ValueError("invalid handle payload shape")
            payload = _payload(cast(dict[str, object], raw))
            self._validate_bindings(payload, query)
            return payload
        except (JSONDecodeError, KeyError, TypeError, UnicodeDecodeError, ValueError) as error:
            if isinstance(error, SelectionHandleValidationError):
                raise
            raise SelectionHandleValidationError("selection handle is invalid") from error

    def _validate_bindings(
        self,
        payload: ResourceSelectionHandlePayloadV1,
        query: ResolveSelectionHandleQuery,
    ) -> None:
        now_ms = self._now_ms()
        checks = (
            payload.schema_version == 1,
            hmac.compare_digest(payload.service_instance_id, self._service_instance_id),
            hmac.compare_digest(payload.session_digest, query.session_digest),
            hmac.compare_digest(payload.account_id, query.account_id),
            payload.issued_at_ms >= 0,
            payload.expires_at_ms > payload.issued_at_ms,
            payload.issued_at_ms <= now_ms < payload.expires_at_ms,
            bool(payload.connector_id and payload.resource_type and payload.resource_id),
        )
        if not all(checks):
            raise SelectionHandleValidationError("selection handle binding mismatch")
        expected = (
            (query.expected_connector_id, payload.connector_id),
            (query.expected_resource_type, payload.resource_type),
            (query.expected_resource_id, payload.resource_id),
        )
        if any(required is not None and required != actual for required, actual in expected):
            raise SelectionHandleValidationError("selection handle identity mismatch")
        if (
            query.require_parent_match
            and query.expected_parent_resource_id != payload.parent_resource_id
        ):
            raise SelectionHandleValidationError("selection handle parent mismatch")


def _decode_base64url(value: str) -> bytes:
    if not value or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for char in value
    ):
        raise ValueError("invalid base64url value")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _payload(raw: dict[str, object]) -> ResourceSelectionHandlePayloadV1:
    if raw["schema_version"] != 1:
        raise ValueError("invalid payload schema version")
    optional_text = ("parent_resource_id", "version_token")
    for field in optional_text:
        if raw[field] is not None and not isinstance(raw[field], str):
            raise TypeError(f"{field} must be a string or null")
    text_fields = (
        "service_instance_id",
        "session_digest",
        "account_id",
        "connector_id",
        "resource_type",
        "resource_id",
    )
    if any(not isinstance(raw[field], str) for field in text_fields):
        raise TypeError("payload identity fields must be strings")
    if type(raw["issued_at_ms"]) is not int or type(raw["expires_at_ms"]) is not int:
        raise TypeError("payload timestamps must be integers")
    return ResourceSelectionHandlePayloadV1(
        schema_version=1,
        service_instance_id=cast(str, raw["service_instance_id"]),
        session_digest=cast(str, raw["session_digest"]),
        account_id=cast(str, raw["account_id"]),
        connector_id=cast(str, raw["connector_id"]),
        resource_type=cast(str, raw["resource_type"]),
        resource_id=cast(str, raw["resource_id"]),
        parent_resource_id=cast(str | None, raw["parent_resource_id"]),
        version_token=cast(str | None, raw["version_token"]),
        issued_at_ms=cast(int, raw["issued_at_ms"]),
        expires_at_ms=cast(int, raw["expires_at_ms"]),
    )
