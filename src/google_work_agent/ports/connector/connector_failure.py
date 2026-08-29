"""Canonical connector-boundary failure contract and normalization.

Provider and MCP concrete exceptions are normalized here before crossing into
the API layer. HTTP semantics deliberately remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPClientPortError,
    MCPClientPortErrorCode,
)
from google_work_agent.ports.system.attachment_staging_port import AttachmentStagingError


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


def normalize_google_workspace_failure(
    error: GoogleWorkspaceGatewayError,
) -> ConnectorOperationFailure:
    mapping = {
        GoogleWorkspaceErrorCode.INVALID_ARGUMENT: (
            ConnectorFailureCode.INVALID_ARGUMENT,
            False,
        ),
        GoogleWorkspaceErrorCode.AUTH_EXPIRED: (ConnectorFailureCode.AUTH_REQUIRED, False),
        GoogleWorkspaceErrorCode.PERMISSION_DENIED: (
            ConnectorFailureCode.PERMISSION_DENIED,
            False,
        ),
        GoogleWorkspaceErrorCode.NOT_FOUND: (ConnectorFailureCode.NOT_FOUND, False),
        GoogleWorkspaceErrorCode.RATE_LIMITED: (ConnectorFailureCode.RATE_LIMITED, True),
        GoogleWorkspaceErrorCode.UPSTREAM_5XX: (
            ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
            True,
        ),
        GoogleWorkspaceErrorCode.TIMEOUT: (ConnectorFailureCode.TIMEOUT, True),
        GoogleWorkspaceErrorCode.CONNECTION_CLOSED: (
            ConnectorFailureCode.CONNECTION_UNAVAILABLE,
            True,
        ),
        GoogleWorkspaceErrorCode.RESPONSE_MALFORMED: (
            ConnectorFailureCode.MALFORMED_RESPONSE,
            False,
        ),
    }
    code, retryable = mapping.get(
        error.code,
        (ConnectorFailureCode.UPSTREAM_UNAVAILABLE, False),
    )
    return ConnectorOperationFailure(
        code=code,
        detail_code=f"CONNECTOR_{error.code.value}",
        retryable=retryable,
    )


def normalize_attachment_staging_failure(
    error: AttachmentStagingError,
) -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.ATTACHMENT_INVALID,
        detail_code=error.safe_code,
        retryable=False,
    )


def normalize_mcp_transport_failure(error: MCPClientPortError) -> ConnectorOperationFailure:
    if error.code is MCPClientPortErrorCode.CONFIGURATION_ERROR:
        detail = str(error)
        if detail != "GOOGLE_OAUTH_CLIENT_ID_MISSING":
            detail = "CONNECTOR_CONFIGURATION_INVALID"
        return ConnectorOperationFailure(
            code=ConnectorFailureCode.CONFIGURATION_ERROR,
            detail_code=detail,
            retryable=False,
        )
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.CONNECTION_UNAVAILABLE,
        detail_code=f"MCP_{error.code.value}",
        retryable=True,
    )
