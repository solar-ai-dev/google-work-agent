"""Application boundary for durable write execution claims."""

from dataclasses import dataclass

from google_work_agent.domain.claim.guards.claim_execution import ClaimExecutionGuardInput, guard_claim_execution
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode


@dataclass(frozen=True, slots=True)
class ClaimExecutionCommand:
    guard: ClaimExecutionGuardInput
    expected_version: int


@dataclass(frozen=True, slots=True)
class ClaimExecutionResult:
    applied: bool
    result_code: ResultCode
    current_status: ActionStatus
    current_version: int
    next_allowed_commands: tuple[ActionCommand, ...]
    conflict_detail: str | None = None


class ClaimExecutionHandler:
    """Authorize the domain claim.

    Durable Approval consumption and ExecutionAttempt insertion remain the
    persistence Closure responsibility; this boundary does not dispatch writes.
    """

    def __call__(self, command: ClaimExecutionCommand) -> ClaimExecutionResult:
        guard_claim_execution(command.guard)
        result = transition_claim_execution(
            command.guard.action_status,
            command.guard.action_version,
            command.expected_version,
            effect_type=command.guard.effect_type,
        )
        return ClaimExecutionResult(
            applied=result.applied,
            result_code=result.result_code,
            current_status=result.current_status,
            current_version=result.current_version,
            next_allowed_commands=result.next_allowed_commands,
            conflict_detail=result.conflict_detail,
        )
