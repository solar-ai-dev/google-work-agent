"""Bounded process-local SSE projection replay boundary."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator


class _ClosedSseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


type RunSseEventTypeV1 = Literal[
    "run_status",
    "phase_changed",
    "tool_routing",
    "retrieval_progress",
    "confirmation_required",
    "analysis_progress",
    "plan_updated",
    "approval_required",
    "action_status",
    "verification_result",
    "reauth_required",
    "recovery_required",
    "completed",
    "error",
]

RUN_SSE_EVENT_TYPES_V1 = frozenset(
    {
        "run_status",
        "phase_changed",
        "tool_routing",
        "retrieval_progress",
        "confirmation_required",
        "analysis_progress",
        "plan_updated",
        "approval_required",
        "action_status",
        "verification_result",
        "reauth_required",
        "recovery_required",
        "completed",
        "error",
    }
)


class RunStatusSsePayloadV1(_ClosedSseModel):
    status: Literal[
        "CREATED",
        "ANALYZING",
        "RETRIEVING",
        "WAITING_CONFIRMATION",
        "PLANNING",
        "WAITING_APPROVAL",
        "EXECUTING",
        "VERIFYING",
        "COMPLETED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "REAUTH_REQUIRED",
        "RECOVERY_REQUIRED",
        "FAILED",
        "BLOCKED",
    ]
    snapshot_version: StrictInt


class PhaseChangedSsePayloadV1(_ClosedSseModel):
    phase: Literal[
        "INITIALIZE",
        "REQUEST_ANALYSIS",
        "TOOL_ROUTING",
        "WAITING_CONFIRMATION",
        "CONTEXT_RETRIEVAL",
        "WORK_ANALYSIS",
        "SOLUTION_PLANNING",
        "PLAN_REVIEW",
        "DOMAIN_VALIDATION",
        "WAITING_APPROVAL",
        "PREFLIGHT",
        "ACTION_EXECUTION",
        "READ_EXECUTION",
        "VERIFICATION",
        "RESPONSE_SYNTHESIS",
        "RECOVERY",
        "FINALIZE",
    ]


class ToolRoutingSsePayloadV1(_ClosedSseModel):
    route_revision: StrictInt
    input_route_count: StrictInt
    output_mode: Literal["ANSWER", "ACTION"]


class RetrievalProgressSsePayloadV1(_ClosedSseModel):
    coverage: Literal["NONE", "PARTIAL", "SUFFICIENT"]
    completed_sources: StrictInt
    total_sources: StrictInt


class ConfirmationRequiredSsePayloadV1(_ClosedSseModel):
    interrupt_id: StrictStr
    question: StrictStr
    options: list[StrictStr]


class AnalysisProgressSsePayloadV1(_ClosedSseModel):
    completed_stage: StrictStr


class PlanUpdatedSsePayloadV1(_ClosedSseModel):
    plan_id: StrictStr | None
    revision_no: StrictInt


class ApprovalRequiredSsePayloadV1(_ClosedSseModel):
    action_ids: list[StrictStr]


class ActionStatusSsePayloadV1(_ClosedSseModel):
    action_id: StrictStr
    status: Literal[
        "PROPOSED",
        "MODIFIED",
        "APPROVED",
        "REJECTED",
        "EXPIRED",
        "EXECUTING",
        "UNKNOWN_RESULT",
        "EXECUTED",
        "VERIFIED",
        "FAILED",
        "BLOCKED",
        "DEPENDENCY_BLOCKED",
        "MISMATCH",
        "CANCELLED",
    ]


class VerificationResultSsePayloadV1(_ClosedSseModel):
    action_id: StrictStr
    outcome: Literal["VERIFIED", "MISMATCH"]


class ReauthRequiredSsePayloadV1(_ClosedSseModel):
    connector_id: StrictStr


class _RunRecoveryTargetV1(_ClosedSseModel):
    target_kind: Literal["RUN"]


class _ActionRecoveryTargetV1(_ClosedSseModel):
    target_kind: Literal["ACTION"]
    action_id: StrictStr


class _RecoveryUiProjectionV1(_ClosedSseModel):
    reason_code: Literal[
        "UNKNOWN_RESULT",
        "VERIFICATION_MISMATCH",
        "CHECKPOINT_MISMATCH",
        "CONTRACT_VIOLATION",
    ]
    target: Annotated[
        _RunRecoveryTargetV1 | _ActionRecoveryTargetV1,
        Field(discriminator="target_kind"),
    ]
    allowed_resolution_kinds: list[
        Literal["RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "CANCEL", "FAIL"]
    ]


class RecoveryRequiredSsePayloadV1(_ClosedSseModel):
    recovery: _RecoveryUiProjectionV1


class CompletedSsePayloadV1(_ClosedSseModel):
    status: Literal["COMPLETED", "BLOCKED", "FAILED", "CANCELLED"]
    result_kind: Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]


class ErrorSsePayloadV1(_ClosedSseModel):
    error_code: StrictStr
    recoverable: StrictBool


type SsePayloadV1 = (
    RunStatusSsePayloadV1
    | PhaseChangedSsePayloadV1
    | ToolRoutingSsePayloadV1
    | RetrievalProgressSsePayloadV1
    | ConfirmationRequiredSsePayloadV1
    | AnalysisProgressSsePayloadV1
    | PlanUpdatedSsePayloadV1
    | ApprovalRequiredSsePayloadV1
    | ActionStatusSsePayloadV1
    | VerificationResultSsePayloadV1
    | ReauthRequiredSsePayloadV1
    | RecoveryRequiredSsePayloadV1
    | CompletedSsePayloadV1
    | ErrorSsePayloadV1
)

SSE_PAYLOAD_TYPE_BY_EVENT_V1: dict[RunSseEventTypeV1, type[_ClosedSseModel]] = {
    "run_status": RunStatusSsePayloadV1,
    "phase_changed": PhaseChangedSsePayloadV1,
    "tool_routing": ToolRoutingSsePayloadV1,
    "retrieval_progress": RetrievalProgressSsePayloadV1,
    "confirmation_required": ConfirmationRequiredSsePayloadV1,
    "analysis_progress": AnalysisProgressSsePayloadV1,
    "plan_updated": PlanUpdatedSsePayloadV1,
    "approval_required": ApprovalRequiredSsePayloadV1,
    "action_status": ActionStatusSsePayloadV1,
    "verification_result": VerificationResultSsePayloadV1,
    "reauth_required": ReauthRequiredSsePayloadV1,
    "recovery_required": RecoveryRequiredSsePayloadV1,
    "completed": CompletedSsePayloadV1,
    "error": ErrorSsePayloadV1,
}


def _require_matching_payload(event_type: RunSseEventTypeV1, payload: SsePayloadV1) -> None:
    expected = SSE_PAYLOAD_TYPE_BY_EVENT_V1[event_type]
    if type(payload) is not expected:
        raise ValueError(f"{event_type} requires {expected.__name__}")


class RunSseEventV1(_ClosedSseModel):
    schema_version: Literal[1]
    event_id: StrictStr
    run_id: StrictStr
    action_id: StrictStr | None
    occurred_at_ms: StrictInt
    event_type: RunSseEventTypeV1
    payload: SsePayloadV1
    projection_version: StrictInt

    @model_validator(mode="after")
    def validate_payload_mapping(self) -> RunSseEventV1:
        _require_matching_payload(self.event_type, self.payload)
        return self


class SseEventPageV1(_ClosedSseModel):
    schema_version: Literal[1]
    events: tuple[RunSseEventV1, ...]
    next_event_id: StrictStr | None
    cursor_status: Literal["OK", "CURSOR_EXPIRED"]


class SseEventBufferPort(Protocol):
    def append(self, event: RunSseEventV1) -> None: ...
    def list_after(self, run_id: str, last_event_id: str | None, limit: int) -> SseEventPageV1: ...
    def clear_run(self, run_id: str) -> None: ...


__all__ = [
    "ActionStatusSsePayloadV1",
    "AnalysisProgressSsePayloadV1",
    "ApprovalRequiredSsePayloadV1",
    "CompletedSsePayloadV1",
    "ConfirmationRequiredSsePayloadV1",
    "ErrorSsePayloadV1",
    "PhaseChangedSsePayloadV1",
    "PlanUpdatedSsePayloadV1",
    "RUN_SSE_EVENT_TYPES_V1",
    "ReauthRequiredSsePayloadV1",
    "RecoveryRequiredSsePayloadV1",
    "RetrievalProgressSsePayloadV1",
    "RunSseEventTypeV1",
    "RunSseEventV1",
    "RunStatusSsePayloadV1",
    "SSE_PAYLOAD_TYPE_BY_EVENT_V1",
    "SseEventBufferPort",
    "SseEventPageV1",
    "SsePayloadV1",
    "ToolRoutingSsePayloadV1",
    "VerificationResultSsePayloadV1",
]
