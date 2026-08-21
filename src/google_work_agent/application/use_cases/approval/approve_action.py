"""Application boundary for explicit Action approval authorization."""

from dataclasses import dataclass

from google_work_agent.domain.approval.transitions.approve_action import transition_approve_action
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode


@dataclass(frozen=True, slots=True)
class ApproveActionCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType
    plan_review_passed: bool


@dataclass(frozen=True, slots=True)
class ApproveActionResult:
    applied: bool
    result_code: ResultCode
    current_status: ActionStatus
    current_version: int
    next_allowed_commands: tuple[ActionCommand, ...]
    conflict_detail: str | None = None


class ApproveActionHandler:
    def __call__(self, command: ApproveActionCommand) -> ApproveActionResult:
        result = transition_approve_action(
            command.current_status,
            command.current_version,
            command.expected_version,
            effect_type=command.effect_type,
            plan_review_passed=command.plan_review_passed,
        )
        return ApproveActionResult(
            applied=result.applied,
            result_code=result.result_code,
            current_status=result.current_status,
            current_version=result.current_version,
            next_allowed_commands=result.next_allowed_commands,
            conflict_detail=result.conflict_detail,
        )
