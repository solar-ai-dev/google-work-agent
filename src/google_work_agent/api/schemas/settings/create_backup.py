"""Canonical backup creation wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class CreateBackupRequestV1(ApiModel):
    schema_version: Literal[1]
    command_id: str


class BackupResponse(ApiModel):
    schema_version: Literal[1]
    backup_ref: str
    created_at_ms: int
    size_bytes: int
    manifest_hash: str


__all__ = ["BackupResponse", "CreateBackupRequestV1"]
