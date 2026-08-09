"""Run API schemas."""

from typing import Literal

from pydantic import Field, model_validator

from .common import ApiModel, ContractVersionedRequest


class SelectedResourceRefModel(ApiModel):
    source: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None = None


class StartRunRequest(ContractVersionedRequest):
    command_id: str
    conversation_id: str
    user_message_id: str
    run_id: str
    workflow_key: str
    request_text: str
    entry_mode: str
    selected_resource_ids: list[str]
    selected_resources: list[SelectedResourceRefModel] = Field(default_factory=list)
    requested_mode: str


class ConfirmationResponseV1(ContractVersionedRequest):
    command_id: str
    expected_version: int
    interrupt_id: str
    response_kind: Literal["OPTION_SELECTION", "FREE_TEXT"]
    selected_option_ids: list[str] = Field(default_factory=list)
    free_text: str | None = None

    @model_validator(mode="after")
    def validate_response_choice(self) -> "ConfirmationResponseV1":
        if self.response_kind == "OPTION_SELECTION":
            if not self.selected_option_ids or self.free_text:
                raise ValueError("OPTION_SELECTION requires options and forbids free_text")
        elif self.selected_option_ids or not self.free_text or not self.free_text.strip():
            raise ValueError("FREE_TEXT requires text and forbids selected options")
        return self


class ResumeRunRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    resume_kind: Literal["REAUTH_COMPLETED", "SAFE_CHECKPOINT_RESUME", "RECOVERY_RECHECK"]


class CancelRunRequestV2(ContractVersionedRequest):
    command_id: str
    expected_run_version: int


class ResolveRecoveryRequestV1(ContractVersionedRequest):
    command_id: str
    expected_version: int
    action_id: str
    resolution_kind: Literal["ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN"]


class RunCommandResponse(ApiModel):
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    should_enqueue: bool | None = None
    request_replayed: bool | None = None
    conflict_detail: str | None = None
    result_kind: str | None = None


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


class RunContextResponse(ApiModel):
    context: dict[str, object] | None
    api_contract_version: str
