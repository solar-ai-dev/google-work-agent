"""Canonical token-free Google connection projection."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class ConnectionMetadataV1(ApiModel):
    schema_version: Literal[1]
    connector_id: str
    account_id: str | None
    display_email: str | None
    connection_status: Literal[
        "CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"
    ]
    granted_scopes: list[str]
    missing_required_scopes: list[str]


__all__ = ["ConnectionMetadataV1"]
