"""Application boundary for Action rejection authorization."""

from dataclasses import dataclass
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult

@dataclass(frozen=True, slots=True)
class RejectActionCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType

RejectActionResult = CommandResult[ActionStatus, ActionCommand]

class RejectActionHandler:
    def __call__(self, command: RejectActionCommand) -> RejectActionResult:
        return transition_reject_action(command.current_status, command.current_version, command.expected_version, effect_type=command.effect_type)
