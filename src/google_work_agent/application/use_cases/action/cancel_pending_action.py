"""Application boundary for pending Action cancellation authorization."""

from dataclasses import dataclass
from google_work_agent.domain.action.transitions.cancel_pending_action import transition_cancel_pending_action
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult

@dataclass(frozen=True, slots=True)
class CancelPendingActionCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType

CancelPendingActionResult = CommandResult[ActionStatus, ActionCommand]

class CancelPendingActionHandler:
    def __call__(self, command: CancelPendingActionCommand) -> CancelPendingActionResult:
        return transition_cancel_pending_action(command.current_status, command.current_version, command.expected_version, effect_type=command.effect_type)
