"""Action route schemas."""

from .common import ApiModel, ContractVersionedRequest


class ApproveActionRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    expected_version: int
    approved_by_account_id: str
    approved_by_display: str | None = None
    source_snapshot: dict[str, object]
    approval_id: str
    idempotency_key: str
    ttl_ms: int = 30000


class ModifyActionRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    expected_version: int


class RejectActionRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    expected_version: int


class PrepareRetryRequest(ContractVersionedRequest):
    command_id: str
    request_hash: str
    expected_action_version: int


class ActionCommandResponse(ApiModel):
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: list[str]
    conflict_detail: str | None = None
