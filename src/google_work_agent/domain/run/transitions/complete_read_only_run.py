"""Complete a legacy READ-only Run after every child has settled."""

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected


def transition_complete_read_only_run(
    current_status: RunStatus,
    *,
    plan_status: PlanStatus,
    action_statuses: tuple[ActionStatus, ...],
) -> tuple[RunStatus, PlanStatus]:
    if current_status is not RunStatus.EXECUTING:
        raise RunTransitionRejected("CompleteReadOnlyRun requires Run EXECUTING")
    if plan_status is not PlanStatus.ACTIVE:
        raise RunTransitionRejected("CompleteReadOnlyRun requires current Plan ACTIVE")
    terminal_read_statuses = {
        ActionStatus.VERIFIED,
        ActionStatus.FAILED,
        ActionStatus.REJECTED,
        ActionStatus.CANCELLED,
        ActionStatus.BLOCKED,
        ActionStatus.DEPENDENCY_BLOCKED,
        ActionStatus.EXPIRED,
        ActionStatus.MISMATCH,
    }
    if not action_statuses or any(
        status not in terminal_read_statuses for status in action_statuses
    ):
        raise RunTransitionRejected("CompleteReadOnlyRun requires every READ Action settled")
    return RunStatus.COMPLETED, PlanStatus.COMPLETED
