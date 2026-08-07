"""Run API schemas."""

from .common import ApiModel, ContractVersionedRequest


class StartRunRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    conversation_id: str
    user_message_id: str
    run_id: str
    workflow_key: str
    request_text: str
    entry_mode: str
    selected_resource_ids: list[str]
    requested_mode: str


class ResumeRunRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    resume_kind: str
    resume_payload: dict[str, object] = {}


class CancelRunRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    expected_run_version: int


class RunCommandResponse(ApiModel):
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    should_enqueue: bool | None = None
    request_replayed: bool | None = None
    conflict_detail: str | None = None


class StartRunResponseModel(ApiModel):
    applied: bool
    result_code: str
    run_id: str
    conversation_id: str
    run_status: str
    run_version: int
    user_message_id: str
    workflow_key: str
    enqueued: bool
    request_replayed: bool
    conflict_detail: str | None = None


class RunSnapshotResponse(ApiModel):
    snapshot: dict[str, object]
    api_contract_version: str
