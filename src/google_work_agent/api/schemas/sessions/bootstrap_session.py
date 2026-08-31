"""Bootstrap-session wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class BootstrapSessionRequest(ApiModel):
    schema_version: Literal[1]
    bootstrap_secret: str
    frontend_api_contract_version: str


class BootstrapSessionResponse(ApiModel):
    schema_version: Literal[1] = 1
    session_established: bool
    service_instance_id: str
    api_contract_version: str
    compatibility: Literal["COMPATIBLE", "INCOMPATIBLE"]
