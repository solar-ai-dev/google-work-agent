"""Disconnect-Google response contract."""

from google_work_agent.api.schemas.model import ApiModel


class GoogleDisconnectResponse(ApiModel):
    disconnected: bool
    credential_deleted: bool
    revoke_attempted: bool
    revoke_succeeded: bool
    credential_state: str
    api_contract_version: str
