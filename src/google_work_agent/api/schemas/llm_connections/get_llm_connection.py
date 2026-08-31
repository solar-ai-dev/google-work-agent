"""Canonical token-free LLM credential status projection."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class LlmCredentialStatusV1(ApiModel):
    schema_version: Literal[1]
    provider: str
    configured: bool
    storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None
    validation_status: Literal["VALID", "INVALID", "UNAVAILABLE", "NOT_CONFIGURED"]


__all__ = ["LlmCredentialStatusV1"]
