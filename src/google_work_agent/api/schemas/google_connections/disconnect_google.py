"""Canonical Google revoke wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class RevokeConnectionRequestV1(ApiModel):
    schema_version: Literal[1]
    command_id: str


class RevokeResultV1(ApiModel):
    schema_version: Literal[1]
    revocation_attempted: bool
    local_credential_deleted: bool
    connection_status: Literal["DISCONNECTED", "UNAVAILABLE"]


__all__ = ["RevokeConnectionRequestV1", "RevokeResultV1"]
