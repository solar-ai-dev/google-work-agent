"""Canonical preconditions for claiming external write execution."""

from dataclasses import dataclass

from google_work_agent.domain.enums import ActionStatus, ApprovalStatus, EffectType, RunStatus
from google_work_agent.domain.exceptions import PolicyViolationError


@dataclass(frozen=True, slots=True)
class ClaimExecutionGuardInput:
    action_status: ActionStatus
    effect_type: EffectType
    action_version: int
    approval_status: ApprovalStatus
    approval_action_version: int
    approval_arguments_hash: str
    current_arguments_hash: str
    approval_source_snapshot_hash: str
    current_source_snapshot_hash: str
    approval_policy_version: str
    current_policy_version: str
    approval_tool_schema_version: str
    current_tool_schema_version: str
    expires_at_ms: int
    now_ms: int
    run_status: RunStatus
    durable_cancel_intent: bool
    plan_superseded: bool
    predecessor_verified: bool
    active_attempt_exists: bool


def guard_claim_execution(value: ClaimExecutionGuardInput) -> None:
    if value.effect_type is EffectType.READ:
        raise PolicyViolationError("READ action cannot acquire a write claim")
    if value.action_status is not ActionStatus.APPROVED:
        raise PolicyViolationError("write claim requires APPROVED action")
    if value.approval_status is not ApprovalStatus.ACTIVE:
        raise PolicyViolationError("write claim requires ACTIVE approval")
    if value.action_version != value.approval_action_version:
        raise PolicyViolationError("approval action version is stale")
    if value.approval_arguments_hash != value.current_arguments_hash:
        raise PolicyViolationError("approval arguments binding is stale")
    if value.approval_source_snapshot_hash != value.current_source_snapshot_hash:
        raise PolicyViolationError("approval source snapshot is stale")
    if value.approval_policy_version != value.current_policy_version:
        raise PolicyViolationError("approval policy version is stale")
    if value.approval_tool_schema_version != value.current_tool_schema_version:
        raise PolicyViolationError("approval tool schema version is stale")
    if value.now_ms >= value.expires_at_ms:
        raise PolicyViolationError("approval expired")
    if value.durable_cancel_intent or value.run_status in {RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED, RunStatus.RECOVERY_REQUIRED}:
        raise PolicyViolationError("run state forbids a new write claim")
    if value.plan_superseded:
        raise PolicyViolationError("superseded plan cannot issue a write claim")
    if not value.predecessor_verified:
        raise PolicyViolationError("action dependency is not VERIFIED")
    if value.active_attempt_exists:
        raise PolicyViolationError("approval already has an active execution attempt")
