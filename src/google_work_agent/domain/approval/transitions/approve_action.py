"""Canonical Approval activation transition for a write Action."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode
from google_work_agent.domain.results import CommandResult

_ALLOWED = frozenset({ActionStatus.PROPOSED, ActionStatus.MODIFIED})


def transition_approve_action(current_status: ActionStatus, current_version: int, expected_version: int, *, effect_type: EffectType, plan_review_passed: bool) -> CommandResult[ActionStatus, ActionCommand]:
    if effect_type is EffectType.READ:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "READ actions do not use Approval")
    if not plan_review_passed:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "plan review must be PASSED")
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status not in _ALLOWED:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), f"APPROVE_ACTION is not allowed from {current_status.value}")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.APPROVED, current_version + 1, ())
