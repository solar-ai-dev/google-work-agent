"""Get-readiness wire contract."""

from google_work_agent.api.schemas.common import ApiModel


class ReadyResponse(ApiModel):
    status: str
    checks: list[dict[str, object]]
    release_version: str
    api_contract_version: str
    occurred_at_ms: int
