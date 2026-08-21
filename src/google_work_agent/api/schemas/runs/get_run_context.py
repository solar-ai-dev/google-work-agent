"""Get-run-context wire response."""

from google_work_agent.api.schemas.common import ApiModel


class RunContextResponse(ApiModel):
    context: dict[str, object] | None
    api_contract_version: str
