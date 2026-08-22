"""Get-runtime-summary wire contract."""

from google_work_agent.api.schemas.common import ApiModel


class RuntimeSummaryResponse(ApiModel):
    summary: dict[str, object]
    api_contract_version: str
