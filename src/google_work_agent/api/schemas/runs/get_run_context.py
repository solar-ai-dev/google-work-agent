"""Get-run-context wire response."""

from google_work_agent.api.schemas.model import ApiModel


class RunContextResponse(ApiModel):
    context: dict[str, object] | None
    api_contract_version: str
