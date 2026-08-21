"""Application boundary for Action modification authorization."""

from dataclasses import dataclass
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.enums import ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.commands import ActionCommand

@dataclass(frozen=True, slots=True)
class ModifyActionCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType

ModifyActionResult = CommandResult[ActionStatus, ActionCommand]

class ModifyActionHandler:
    def __call__(self, command: ModifyActionCommand) -> ModifyActionResult:
        return transition_modify_action(command.current_status, command.current_version, command.expected_version, effect_type=command.effect_type)
