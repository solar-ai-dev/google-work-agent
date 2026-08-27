"""Canonical Run transition for finalize cancel."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.finalize_cancel import guard_finalize_cancel
from google_work_agent.domain.run.model import RunStatusV1


def transition_finalize_cancel(
    current_status: RunStatusV1,
    *,
    cancel_intent_active: bool,
    plan_status: PlanStatusV1 | None,
    plan_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    approval_statuses: tuple[ApprovalStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_finalize_cancel(
        current_status,
        cancel_intent_active=cancel_intent_active,
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        action_statuses=action_statuses,
        approval_statuses=approval_statuses,
        attempt_statuses=attempt_statuses,
    )
    return RunStatusV1.CANCELLED
