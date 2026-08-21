"""Application boundary for explicit Action approval authorization."""

from dataclasses import dataclass
from google_work_agent.domain.approval.transitions.approve_action import transition_approve_action
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult

@dataclass(frozen=True, slots=True)
class ApproveActionCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType
    plan_review_passed: bool

ApproveActionResult = CommandResult[ActionStatus, ActionCommand]

class ApproveActionHandler:
    def __call__(self, command: ApproveActionCommand) -> ApproveActionResult:
        return transition_approve_action(command.current_status, command.current_version, command.expected_version, effect_type=command.effect_type, plan_review_passed=command.plan_review_passed)
