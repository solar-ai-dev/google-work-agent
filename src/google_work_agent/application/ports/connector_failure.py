"""Application-level connector failure contract.

Provider and MCP concrete exceptions are normalized to this contract before
crossing into the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConnectorFailureCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CONNECTION_UNAVAILABLE = "CONNECTION_UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    ATTACHMENT_INVALID = "ATTACHMENT_INVALID"


@dataclass(frozen=True, slots=True)
class ConnectorOperationFailure(RuntimeError):
    code: ConnectorFailureCode
    detail_code: str
    retryable: bool = False
    safe_description: str | None = None

    def __str__(self) -> str:
        return self.detail_code
