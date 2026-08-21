"""Application boundary for FAILED write retry preparation."""

from dataclasses import dataclass
from google_work_agent.domain.action.transitions.prepare_write_retry import transition_prepare_write_retry
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult

@dataclass(frozen=True, slots=True)
class PrepareWriteRetryCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType

PrepareWriteRetryResult = CommandResult[ActionStatus, ActionCommand]

class PrepareWriteRetryHandler:
    def __call__(self, command: PrepareWriteRetryCommand) -> PrepareWriteRetryResult:
        return transition_prepare_write_retry(command.current_status, command.current_version, command.expected_version, effect_type=command.effect_type)
