"""Application boundary for durable write execution claims."""

from dataclasses import dataclass
from google_work_agent.domain.claim.guards.claim_execution import ClaimExecutionGuardInput, guard_claim_execution
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult

@dataclass(frozen=True, slots=True)
class ClaimExecutionCommand:
    guard: ClaimExecutionGuardInput
    expected_version: int

ClaimExecutionResult = CommandResult[ActionStatus, ActionCommand]

class ClaimExecutionHandler:
    """Authorize the domain claim. Persistence must atomically consume Approval and insert Attempt."""
    def __call__(self, command: ClaimExecutionCommand) -> ClaimExecutionResult:
        guard_claim_execution(command.guard)
        return transition_claim_execution(command.guard.action_status, command.guard.action_version, command.expected_version, effect_type=command.guard.effect_type)
