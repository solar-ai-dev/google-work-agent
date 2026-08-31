"""Canonical graceful-shutdown wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class RequestShutdownRequestV1(ApiModel):
    schema_version: Literal[1]
    command_id: str


class ShutdownResponse(ApiModel):
    schema_version: Literal[1]
    accepted: bool


__all__ = ["RequestShutdownRequestV1", "ShutdownResponse"]
