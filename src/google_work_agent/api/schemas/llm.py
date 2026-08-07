"""LLM runtime API schemas."""

from __future__ import annotations

from .common import ApiModel


class LLMConnectionResponse(ApiModel):
    llm: dict[str, object]
    api_contract_version: str


class StoreLLMApiKeyRequest(ApiModel):
    api_key: str
    storage_mode: str


class DeleteLLMApiKeyResponse(ApiModel):
    credential_state: str
    api_contract_version: str


class StoreLLMApiKeyResponse(ApiModel):
    credential_state: str
    api_contract_version: str


class TestLLMConnectionResponse(ApiModel):
    llm: dict[str, object]
    api_contract_version: str
