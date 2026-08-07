"""Current local identity projection schemas."""

from google_work_agent.api.schemas.common import ApiModel


class CurrentGoogleAccountResponse(ApiModel):
    account: dict[str, object] | None
    api_contract_version: str
