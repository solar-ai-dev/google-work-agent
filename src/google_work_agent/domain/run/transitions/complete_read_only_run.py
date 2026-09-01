"""Complete a legacy READ-only Run after every child has settled."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.complete_read_only_run import (
    guard_complete_read_only_run,
)
from google_work_agent.domain.run.model import RunStatusV1


def transition_complete_read_only_run(
    current_status: RunStatusV1,
    *,
    plan_status: PlanStatusV1,
    action_statuses: tuple[ActionStatusV1, ...],
) -> tuple[RunStatusV1, PlanStatusV1]:
    guard_complete_read_only_run(
        current_status,
        plan_status=plan_status,
        action_statuses=action_statuses,
    )
    return RunStatusV1.COMPLETED, PlanStatusV1.COMPLETED
