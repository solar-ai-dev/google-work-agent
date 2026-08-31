"""Canonical LLM credential store wire contract."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class StoreLLMApiKeyRequest(ApiModel):
    schema_version: Literal[1]
    command_id: str
    api_key: str
    storage_mode: Literal["KEYRING", "SESSION_ONLY"]


__all__ = ["StoreLLMApiKeyRequest"]
