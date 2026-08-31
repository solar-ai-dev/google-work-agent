"""Get-readiness wire contract."""

from google_work_agent.api.schemas.model import ApiModel


class ReadinessCheckResponse(ApiModel):
    name: str
    state: str
    detail: str | None


class ReadyResponse(ApiModel):
    status: str
    checks: list[ReadinessCheckResponse]
    release_version: str
    api_contract_version: str
    occurred_at_ms: int


__all__ = ["ReadinessCheckResponse", "ReadyResponse"]
