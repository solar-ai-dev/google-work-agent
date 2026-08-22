"""Test-LLM-connection response contract."""

from google_work_agent.api.schemas.model import ApiModel


class TestLLMConnectionResponse(ApiModel):
    llm: dict[str, object]
    api_contract_version: str
