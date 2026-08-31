"""Canonical bounded backup inventory projection."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel
from google_work_agent.api.schemas.settings.create_backup import BackupResponse


class BackupListResponse(ApiModel):
    schema_version: Literal[1]
    items: list[BackupResponse]


__all__ = ["BackupListResponse"]
