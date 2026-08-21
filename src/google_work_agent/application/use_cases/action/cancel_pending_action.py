"""Application boundary for pending Action cancellation authorization."""

from dataclasses import dataclass

from google_work_agent.domain.action.transitions.cancel_pending_action import transition_cancel_pending_action
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode


@dataclass(frozen=True, slots=True)
class CancelPendingActionCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType


@dataclass(frozen=True, slots=True)
class CancelPendingActionResult:
    applied: bool
    result_code: ResultCode
    current_status: ActionStatus
    current_version: int
    next_allowed_commands: tuple[ActionCommand, ...]
    conflict_detail: str | None = None


class CancelPendingActionHandler:
    def __call__(self, command: CancelPendingActionCommand) -> CancelPendingActionResult:
        result = transition_cancel_pending_action(
            command.current_status,
            command.current_version,
            command.expected_version,
            effect_type=command.effect_type,
        )
        return CancelPendingActionResult(
            applied=result.applied,
            result_code=result.result_code,
            current_status=result.current_status,
            current_version=result.current_version,
            next_allowed_commands=result.next_allowed_commands,
            conflict_detail=result.conflict_detail,
        )
