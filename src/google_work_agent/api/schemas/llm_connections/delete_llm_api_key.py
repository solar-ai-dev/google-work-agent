"""Delete-LLM-API-key response contract."""

from google_work_agent.api.schemas.model import ApiModel


class DeleteLLMApiKeyResponse(ApiModel):
    credential_state: str
    api_contract_version: str
