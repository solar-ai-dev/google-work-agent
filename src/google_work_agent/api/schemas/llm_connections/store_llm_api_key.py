"""Store-LLM-API-key wire contracts."""

from google_work_agent.api.schemas.model import ApiModel


class StoreLLMApiKeyRequest(ApiModel):
    api_key: str
    storage_mode: str


class StoreLLMApiKeyResponse(ApiModel):
    credential_state: str
    api_contract_version: str
