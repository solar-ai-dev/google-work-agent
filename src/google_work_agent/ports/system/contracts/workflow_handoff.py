"""Canonical durable workflow-handoff contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type JsonObject = dict[str, object]
type GraphProfileIdV1 = Literal["SINGLE_BASELINE", "THREE_STAGE", "SIX_ROLE_BASELINE"]
type RequestedModeV1 = Literal["AUTO", "LOCAL_GPU", "API_LLM"]
type WorkflowHandoffStatusV1 = Literal[
    "PENDING", "DISPATCHED", "CONSUMED", "BLOCKED_BINDING", "SUPERSEDED"
]
type WorkflowSubmitReasonV1 = Literal[
    "ALREADY_RUNNING", "NOT_COMMITTED", "BINDING_MISMATCH", "SHUTTING_DOWN"
]
type WorkflowExecutionReleaseReasonV1 = Literal[
    "ALREADY_RUNNING",
    "NOT_COMMITTED",
    "BINDING_MISMATCH",
    "SHUTTING_DOWN",
    "AUTHORITY_EPOCH_CHANGED",
]


@dataclass(frozen=True, slots=True)
class AgentNodeResumeTargetV2:
    kind: Literal["AGENT_NODE"]
    semantic_owner_id: str
    compiled_subgraph_id: str
    node_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str


@dataclass(frozen=True, slots=True)
class MainControlResumeTargetV2:
    kind: Literal["MAIN_CONTROL"]
    stage_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str


type RegisteredResumeTargetRefV2 = AgentNodeResumeTargetV2 | MainControlResumeTargetV2


@dataclass(frozen=True, slots=True)
class ConfirmationResumeControlV1:
    kind: Literal["CONFIRMATION_RESPONSE"]
    confirmation_response: JsonObject
    policy_confirmation_receipt: JsonObject | None


@dataclass(frozen=True, slots=True)
class ContextAdjustmentControlV1:
    kind: Literal["CONTEXT_ADJUSTMENT"]
    adjustment: JsonObject


@dataclass(frozen=True, slots=True)
class RetrievalCacheRestartControlV1:
    kind: Literal["RETRIEVAL_CACHE_RESTART"]
    lost_checkpoint_id: str
    lost_handle_fingerprint: str


type WorkflowControlEnvelopeV1 = (
    ConfirmationResumeControlV1 | ContextAdjustmentControlV1 | RetrievalCacheRestartControlV1
)


@dataclass(frozen=True, slots=True)
class RunExecutionRefV1:
    schema_version: Literal[1]
    execution_kind: Literal["START", "RESUME"]
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    requested_mode: RequestedModeV1
    resume_target: RegisteredResumeTargetRefV2 | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("RunExecutionRefV1.schema_version must be 1")
        _validate_execution_binding(
            execution_kind=self.execution_kind,
            checkpoint_id=None if self.execution_kind == "START" else "staged-separately",
            checkpoint_generation=0 if self.execution_kind == "START" else 1,
            resume_target=self.resume_target,
        )


@dataclass(frozen=True, slots=True)
class WorkflowHandoffStageV1:
    schema_version: Literal[1]
    handoff_id: str
    trigger_command_id: str
    execution: RunExecutionRefV1
    checkpoint_id: str | None
    checkpoint_generation: int
    control_kind: Literal[
        "NONE", "CONFIRMATION_RESPONSE", "CONTEXT_ADJUSTMENT", "RETRIEVAL_CACHE_RESTART"
    ]
    control: WorkflowControlEnvelopeV1 | None
    control_payload_hash: str | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("WorkflowHandoffStageV1.schema_version must be 1")
        _validate_execution_binding(
            execution_kind=self.execution.execution_kind,
            checkpoint_id=self.checkpoint_id,
            checkpoint_generation=self.checkpoint_generation,
            resume_target=self.execution.resume_target,
        )
        if self.control_kind == "NONE":
            if self.control is not None or self.control_payload_hash is not None:
                raise ValueError("NONE control cannot carry a payload or hash")
        elif self.control is None or not _is_sha256(self.control_payload_hash):
            raise ValueError("typed control requires a canonical SHA-256 payload hash")
        elif self.control.kind != self.control_kind:
            raise ValueError("control_kind must match the typed control envelope")


@dataclass(frozen=True, slots=True)
class WorkflowExecutionBindingV1:
    schema_version: Literal[1]
    execution_kind: Literal["START", "RESUME"]
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    requested_mode: RequestedModeV1
    checkpoint_id: str | None
    checkpoint_generation: int
    resume_target: RegisteredResumeTargetRefV2 | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("WorkflowExecutionBindingV1.schema_version must be 1")
        _validate_execution_binding(
            execution_kind=self.execution_kind,
            checkpoint_id=self.checkpoint_id,
            checkpoint_generation=self.checkpoint_generation,
            resume_target=self.resume_target,
        )


@dataclass(frozen=True, slots=True)
class WorkflowExecutionAdmissionV1:
    schema_version: Literal[1]
    admission_id: str
    handoff_id: str
    handoff_run_sequence: int
    submission_kind: Literal["NORMAL_HANDOFF", "CONSUMED_CONTINUATION_RECOVERY"]
    effective_binding: WorkflowExecutionBindingV1
    expected_run_version: int

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.handoff_run_sequence < 1:
            raise ValueError("invalid workflow execution admission")
        if self.expected_run_version < 0:
            raise ValueError("expected_run_version must be non-negative")
        if (
            self.submission_kind == "CONSUMED_CONTINUATION_RECOVERY"
            and self.effective_binding.execution_kind != "RESUME"
        ):
            raise ValueError("continuation recovery admission must resume")


@dataclass(frozen=True, slots=True)
class WorkflowHandoffV1:
    schema_version: Literal[1]
    handoff_id: str
    trigger_command_id: str
    execution: RunExecutionRefV1
    checkpoint_id: str | None
    checkpoint_generation: int
    run_sequence: int
    control_kind: Literal[
        "NONE", "CONFIRMATION_RESPONSE", "CONTEXT_ADJUSTMENT", "RETRIEVAL_CACHE_RESTART"
    ]
    control: WorkflowControlEnvelopeV1 | None
    control_payload_hash: str | None
    status: WorkflowHandoffStatusV1
    last_submit_reason: WorkflowSubmitReasonV1 | None
    execution_admission: WorkflowExecutionAdmissionV1 | None
    applied_checkpoint_id: str | None
    applied_checkpoint_generation: int | None
    version: int


@dataclass(frozen=True, slots=True)
class WorkflowExecutionSubmissionV2:
    schema_version: Literal[2]
    admission: WorkflowExecutionAdmissionV1

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValueError("WorkflowExecutionSubmissionV2.schema_version must be 2")


@dataclass(frozen=True, slots=True)
class RunExecutionAcceptedV1:
    schema_version: Literal[1]
    accepted: bool
    reason_code: Literal[
        "ACCEPTED", "ALREADY_RUNNING", "NOT_COMMITTED", "BINDING_MISMATCH", "SHUTTING_DOWN"
    ]


@dataclass(frozen=True, slots=True)
class WorkflowExecutionSettlementV1:
    schema_version: Literal[1]
    outcome: Literal["SETTLED", "AUTHORITY_STALE_RETIRED"]
    handoff: WorkflowHandoffV1


def _validate_execution_binding(
    *,
    execution_kind: str,
    checkpoint_id: str | None,
    checkpoint_generation: int,
    resume_target: RegisteredResumeTargetRefV2 | None,
) -> None:
    if execution_kind == "START":
        if checkpoint_id is not None or checkpoint_generation != 0 or resume_target is not None:
            raise ValueError("START requires no checkpoint and no resume target")
        return
    if execution_kind != "RESUME":
        raise ValueError("execution_kind must be START or RESUME")
    if not checkpoint_id or checkpoint_generation < 1 or resume_target is None:
        raise ValueError("RESUME requires a committed checkpoint and registered target")


def _is_sha256(value: str | None) -> bool:
    return (
        value is not None and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
    )
