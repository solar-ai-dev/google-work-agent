"""Guard for block run."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected, require_status

_ALLOWED = frozenset(
    {
        RunStatusV1.CREATED,
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.WAITING_CONFIRMATION,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.VERIFYING,
    }
)


def guard_block_run(
    current_status: RunStatusV1,
    *,
    plan_status: PlanStatusV1 | None,
    plan_is_current: bool,
    review_disposition: str | None,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
) -> None:
    """Reject a block run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "block_run")
    if plan_status is not None and not plan_is_current:
        raise RunTransitionRejected("BlockRun requires current Plan authority")
    if current_status is RunStatusV1.VERIFYING and review_disposition != "BLOCK":
        raise RunTransitionRejected("BlockRun from VERIFYING requires Review BLOCK")
    unresolved_actions = {
        ActionStatusV1.EXECUTING,
        ActionStatusV1.EXECUTED,
        ActionStatusV1.UNKNOWN_RESULT,
        ActionStatusV1.MISMATCH,
    }
    if any(status in unresolved_actions for status in action_statuses):
        raise RunTransitionRejected("BlockRun requires all dispatched Action facts resolved")
    unresolved_attempts = {
        ExecutionAttemptStatusV1.CLAIMED,
        ExecutionAttemptStatusV1.EXECUTING,
        ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    }
    if any(status in unresolved_attempts for status in attempt_statuses):
        raise RunTransitionRejected("BlockRun requires no unresolved ExecutionAttempt")
