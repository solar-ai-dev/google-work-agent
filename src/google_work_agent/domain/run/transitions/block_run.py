"""Canonical Run transition for block run."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.block_run import guard_block_run
from google_work_agent.domain.run.model import RunStatusV1


def transition_block_run(
    current_status: RunStatusV1,
    *,
    plan_status: PlanStatusV1 | None,
    plan_is_current: bool,
    review_disposition: str | None,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_block_run(
        current_status,
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        review_disposition=review_disposition,
        action_statuses=action_statuses,
        attempt_statuses=attempt_statuses,
    )
    return RunStatusV1.BLOCKED
