"""Approve-action request and command response wire contracts."""

from pydantic import Field

from google_work_agent.api.schemas.model import ApiModel, ContractVersionedRequest


class ApproveActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    # Compatibility-only wire field. Server settings own approval lifetime.
    ttl_ms: int | None = Field(default=None, deprecated=True)
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False


class ActionCommandResponse(ApiModel):
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: list[str]
    conflict_detail: str | None = None
