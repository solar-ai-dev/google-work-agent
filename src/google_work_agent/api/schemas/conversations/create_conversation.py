"""Canonical create-conversation wire request."""

from typing import Literal

from pydantic import Field

from google_work_agent.api.schemas.model import ApiModel


class CreateConversationRequestV1(ApiModel):
    schema_version: Literal[1] = 1
    command_id: str
    title: str | None = Field(default=None, min_length=1, max_length=200)


__all__ = ["CreateConversationRequestV1"]
