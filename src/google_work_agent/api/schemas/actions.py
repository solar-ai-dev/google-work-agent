"""Action route schemas."""

from pydantic import Field

from .common import ApiModel, ContractVersionedRequest


class ApproveActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    ttl_ms: int = 30000
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False


class ModifyActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    # Business argument field names to change, scoped per-tool by the server's
    # Tool Registry (see build_p0_tool_registry). The client never supplies a
    # full Canonical Arguments payload, a hash, or any approval/claim metadata
    # -- those remain server-generated authority values.
    arguments_patch: dict[str, object] = Field(default_factory=dict)


class RejectActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    reason_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )


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
