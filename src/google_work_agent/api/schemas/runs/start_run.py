"""Start-run wire contracts."""

from pydantic import Field

from google_work_agent.api.schemas.model import ApiModel, ContractVersionedRequest


class SelectedResourceRefModel(ApiModel):
    source: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None = None


class StartRunRequest(ContractVersionedRequest):
    command_id: str
    conversation_id: str
    request_text: str
    entry_mode: str
    selected_resource_ids: list[str]
    selected_resources: list[SelectedResourceRefModel] = Field(default_factory=list)
    requested_mode: str


class StartRunResponseModel(ApiModel):
    applied: bool
    result_code: str
    run_id: str
    conversation_id: str
    run_status: str
    run_version: int
    user_message_id: str
    workflow_key: str
    handoff_id: str
    enqueued: bool
    request_replayed: bool
    conflict_detail: str | None = None
