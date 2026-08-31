"""Guard for approving a write Action."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1

_ALLOWED = frozenset({ActionStatusV1.PROPOSED, ActionStatusV1.MODIFIED})
_ALLOWED_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})
_ALLOWED_RUN_STATUSES = frozenset({RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING})


def guard_approve_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_review_passed: bool,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
    run_status: RunStatusV1,
) -> tuple[ResultCode, str] | None:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        allowed_statuses=_ALLOWED_PLAN_STATUSES,
    )
    if authority_conflict is not None:
        return ResultCode.STATE_CONFLICT, authority_conflict
    if run_status not in _ALLOWED_RUN_STATUSES:
        return ResultCode.STATE_CONFLICT, "ApproveAction requires Run WAITING_APPROVAL or VERIFYING"
    if effect_type is EffectType.READ:
        return ResultCode.STATE_CONFLICT, "READ actions do not use Approval"
    if not plan_review_passed:
        return ResultCode.STATE_CONFLICT, "plan review must be PASSED"
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    if current_status not in _ALLOWED:
        return (
            ResultCode.STATE_CONFLICT,
            f"APPROVE_ACTION is not allowed from {current_status.value}",
        )
    return None
