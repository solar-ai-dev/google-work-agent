"""Canonical Action modify transition."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode

_ALLOWED = frozenset(
    {
        ActionStatusV1.PROPOSED,
        ActionStatusV1.APPROVED,
        ActionStatusV1.EXPIRED,
        ActionStatusV1.FAILED,
        ActionStatusV1.MODIFIED,
    }
)


def transition_modify_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status, plan_is_current=plan_is_current
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
            f"MODIFY_ACTION is not allowed from {current_status.value}",
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.MODIFIED, current_version + 1, ()
    )
