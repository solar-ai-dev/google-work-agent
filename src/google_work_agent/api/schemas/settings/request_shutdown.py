"""Request-shutdown wire response."""

from google_work_agent.api.schemas.model import ApiModel


class ShutdownResponse(ApiModel):
    report: dict[str, object]
    api_contract_version: str
