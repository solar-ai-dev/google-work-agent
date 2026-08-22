"""Bootstrap-session wire contracts."""

from google_work_agent.api.schemas.model import ApiModel, ContractVersionedRequest


class BootstrapSessionRequest(ContractVersionedRequest):
    bootstrap_secret: str
    service_instance_id: str


class BootstrapSessionResponse(ApiModel):
    session_established: bool
    service_instance_id: str
    api_contract_version: str
