"""Approve a write Action after a current Plan review passes."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunStatusV1

_ALLOWED = frozenset({ActionStatusV1.PROPOSED, ActionStatusV1.MODIFIED})
_ALLOWED_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})
_ALLOWED_RUN_STATUSES = frozenset({RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING})


def transition_approve_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_review_passed: bool,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
    run_status: RunStatusV1,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        allowed_statuses=_ALLOWED_PLAN_STATUSES,
    )
    if authority_conflict is not None:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            authority_conflict,
        )
    if run_status not in _ALLOWED_RUN_STATUSES:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "ApproveAction requires Run WAITING_APPROVAL or VERIFYING",
        )
    if effect_type is EffectType.READ:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "READ actions do not use Approval",
        )
    if not plan_review_passed:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "plan review must be PASSED",
        )
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    if current_status not in _ALLOWED:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            f"APPROVE_ACTION is not allowed from {current_status.value}",
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.APPROVED, current_version + 1, ()
    )
