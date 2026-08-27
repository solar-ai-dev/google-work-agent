"""Guard for complete write run."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected, require_status

_ALLOWED = frozenset({RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING})


def guard_complete_write_run(
    current_status: RunStatusV1,
    *,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
    unresolved_required_fact_count: int,
    external_write_count: int,
    cancel_intent_active: bool,
) -> None:
    """Reject a complete write run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "complete_write_run")
    if not plan_is_current:
        raise RunTransitionRejected("CompleteWriteRun requires current Plan authority")
    if plan_status not in {PlanStatusV1.WAITING_APPROVAL, PlanStatusV1.ACTIVE}:
        raise RunTransitionRejected("CompleteWriteRun requires a published current Plan")
    if cancel_intent_active:
        raise RunTransitionRejected("CompleteWriteRun is forbidden while cancel intent is active")
    closed = {
        ActionStatusV1.VERIFIED,
        ActionStatusV1.FAILED,
        ActionStatusV1.REJECTED,
        ActionStatusV1.CANCELLED,
        ActionStatusV1.BLOCKED,
        ActionStatusV1.DEPENDENCY_BLOCKED,
    }
    if not action_statuses or any(status not in closed for status in action_statuses):
        raise RunTransitionRejected("CompleteWriteRun requires every planned Action closed")
    unresolved_attempts = {
        ExecutionAttemptStatusV1.CLAIMED,
        ExecutionAttemptStatusV1.EXECUTING,
        ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    }
    if any(status in unresolved_attempts for status in attempt_statuses):
        raise RunTransitionRejected("CompleteWriteRun requires no unresolved ExecutionAttempt")
    if unresolved_required_fact_count != 0:
        raise RunTransitionRejected("CompleteWriteRun requires all execution/verification facts")
    if current_status is RunStatusV1.WAITING_APPROVAL and external_write_count != 0:
        raise RunTransitionRejected(
            "WAITING_APPROVAL completion is allowed only when no external Write started"
        )
