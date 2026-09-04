"""Workflow execution boundary value contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from google_work_agent.ports.system.contracts.workflow_handoff import (
    WorkflowControlEnvelopeV1,
)

type JsonValue = Any


class WorkflowOutcome(StrEnum):
    """External workflow invocation outcomes understood by the coordinator."""

    ACCEPTED = "ACCEPTED"
    ALREADY_RUNNING = "ALREADY_RUNNING"
    COMPLETED = "COMPLETED"
    CHECKPOINT_MISSING = "CHECKPOINT_MISSING"
    DOMAIN_CHECKPOINT_CONFLICT = "DOMAIN_CHECKPOINT_CONFLICT"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class WorkflowCorrelationContext:
    """Correlation metadata forwarded to the workflow runtime."""

    request_id: str
    command_id: str | None
    api_contract_version: str


@dataclass(frozen=True, slots=True)
class SelectedResourceRef:
    """Runtime identity for one user-selected Google resource."""

    source: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowStartRequest:
    """Typed workflow start contract."""

    run_id: str
    conversation_id: str
    workflow_key: str
    entry_mode: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    request_text: str
    selected_resource_ids: tuple[str, ...]
    correlation: WorkflowCorrelationContext
    run_budget: Mapping[str, JsonValue] = field(default_factory=dict)
    selected_resources: tuple[SelectedResourceRef, ...] = ()
    user_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowResumeRequest:
    """Typed workflow resume contract."""

    run_id: str
    workflow_key: str
    resume_kind: str
    resume_payload: dict[str, JsonValue]
    correlation: WorkflowCorrelationContext
    normal_handoff_target_node: str | None = None
    normal_handoff_control: WorkflowControlEnvelopeV1 | None = None


@dataclass(frozen=True, slots=True)
class WorkflowCancelRequest:
    """Typed workflow cancel contract."""

    run_id: str
    workflow_key: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class WorkflowRecoveryRequest:
    """Typed workflow recovery contract."""

    run_id: str
    workflow_key: str
    domain_status: str
    domain_version: int
    correlation: WorkflowCorrelationContext


@dataclass(frozen=True, slots=True)
class WorkflowInvocationResult:
    """Result returned from the workflow runtime."""

    run_id: str
    workflow_key: str
    outcome: WorkflowOutcome
    payload: dict[str, JsonValue]
