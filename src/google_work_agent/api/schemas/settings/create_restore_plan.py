"""Create-restore-plan wire contracts."""

from google_work_agent.api.schemas.model import ApiModel


class RestorePlanRequest(ApiModel):
    backup_id: str


class RestorePlanResponse(ApiModel):
    plan: dict[str, object]
    api_contract_version: str
