"""Action route schemas."""

from .common import ApiModel, ContractVersionedRequest


class ApproveActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    ttl_ms: int = 30000


class ModifyActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int


class RejectActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int


class PrepareRetryRequestV2(ContractVersionedRequest):
    command_id: str
    expected_action_version: int


class ActionCommandResponse(ApiModel):
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: list[str]
    conflict_detail: str | None = None
