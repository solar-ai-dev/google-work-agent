"""Canonical durable Run snapshot wire projection."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel
from google_work_agent.api.schemas.runs.confirm_run import PendingInterruptResponseV1
from google_work_agent.api.schemas.runs.recovery import RecoveryUiProjectionV1


class RunSnapshotRunResponseV1(ApiModel):
    run_id: str
    conversation_id: str
    status: str
    version: int
    entry_mode: str
    requested_mode: str
    actual_runtime: str | None
    started_at_ms: int
    finished_at_ms: int | None
    next_allowed_commands: list[str]


class RunSnapshotMessageResponseV1(ApiModel):
    schema_version: Literal[1]
    id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int


class RunSnapshotActionResponseV1(ApiModel):
    action_id: str
    tool_name: str
    status: str
    version: int
    effect_type: str
    approval_required: bool
    verification_policy: str
    risk: dict[str, object]
    next_allowed_commands: list[str]


class RunSnapshotResponseV1(ApiModel):
    run: RunSnapshotRunResponseV1
    messages: list[RunSnapshotMessageResponseV1]
    current_plan: dict[str, object] | None
    actions: list[RunSnapshotActionResponseV1]
    context_preview: dict[str, object] | None
    pending_interrupt: PendingInterruptResponseV1 | None
    recovery: RecoveryUiProjectionV1 | None
    error: dict[str, object] | None
    external_llm_transfer_scope: dict[str, object] | None
    terminal_result_kind: Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED", "NONE"]
    projection_version: int
    approvals: list[dict[str, object]]
    execution_status: dict[str, object]
    verification_summary: dict[str, object]
    recovery_summary: dict[str, object]


__all__ = [
    "RunSnapshotActionResponseV1",
    "RunSnapshotMessageResponseV1",
    "RunSnapshotResponseV1",
    "RunSnapshotRunResponseV1",
]
