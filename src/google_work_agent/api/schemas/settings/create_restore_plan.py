"""Canonical backup restore wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class RestorePlanRequest(ApiModel):
    schema_version: Literal[1]
    command_id: str
    backup_ref: str


class RestorePlanResponse(ApiModel):
    schema_version: Literal[1]
    backup_ref: str
    status: Literal["RESTORED", "REJECTED"]
    detail_code: str | None


__all__ = ["RestorePlanRequest", "RestorePlanResponse"]
