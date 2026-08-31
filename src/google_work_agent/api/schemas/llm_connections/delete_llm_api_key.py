"""Canonical LLM credential deletion request."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class DeleteLLMApiKeyRequest(ApiModel):
    schema_version: Literal[1]
    command_id: str


__all__ = ["DeleteLLMApiKeyRequest"]
