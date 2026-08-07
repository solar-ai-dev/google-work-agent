"""Runtime and health schemas."""

from .common import ApiModel


class LiveResponse(ApiModel):
    status: str
    service_instance_id: str
    release_version: str
    api_contract_version: str
    occurred_at_ms: int


class ReadyResponse(ApiModel):
    status: str
    checks: list[dict[str, object]]
    release_version: str
    api_contract_version: str
    occurred_at_ms: int


class RuntimeSummaryResponse(ApiModel):
    summary: dict[str, object]
    api_contract_version: str
