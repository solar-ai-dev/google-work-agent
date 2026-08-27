"""Guard for finalize cancel."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected, require_status

_ALLOWED = frozenset(
    {RunStatusV1.CANCEL_REQUESTED, RunStatusV1.VERIFYING, RunStatusV1.REAUTH_REQUIRED}
)


def guard_finalize_cancel(
    current_status: RunStatusV1,
    *,
    cancel_intent_active: bool,
    plan_status: PlanStatusV1 | None,
    plan_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    approval_statuses: tuple[ApprovalStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
) -> None:
    """Reject a finalize cancel request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "finalize_cancel")
    if not cancel_intent_active:
        raise RunTransitionRejected("FinalizeCancel requires durable cancel intent")
    if not plan_is_current or plan_status in {
        PlanStatusV1.SUPERSEDED,
        PlanStatusV1.COMPLETED,
    }:
        raise RunTransitionRejected("FinalizeCancel requires current nonterminal Plan authority")
    unresolved_actions = {
        ActionStatusV1.PROPOSED,
        ActionStatusV1.MODIFIED,
        ActionStatusV1.APPROVED,
        ActionStatusV1.EXPIRED,
        ActionStatusV1.EXECUTING,
        ActionStatusV1.UNKNOWN_RESULT,
        ActionStatusV1.EXECUTED,
    }
    if any(status in unresolved_actions for status in action_statuses):
        raise RunTransitionRejected("FinalizeCancel requires every Action settled")
    unresolved_attempts = {
        ExecutionAttemptStatusV1.CLAIMED,
        ExecutionAttemptStatusV1.EXECUTING,
        ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    }
    if any(status in unresolved_attempts for status in attempt_statuses):
        raise RunTransitionRejected("FinalizeCancel requires no unresolved ExecutionAttempt")
    if any(status is ApprovalStatusV1.ACTIVE for status in approval_statuses):
        raise RunTransitionRejected("FinalizeCancel requires zero ACTIVE Approval")
