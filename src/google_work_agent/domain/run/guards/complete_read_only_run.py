"""Guard for completing a legacy READ-only Run."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def guard_complete_read_only_run(
    current_status: RunStatusV1,
    *,
    plan_status: PlanStatusV1,
    action_statuses: tuple[ActionStatusV1, ...],
) -> None:
    if current_status is not RunStatusV1.EXECUTING:
        raise RunTransitionRejected("CompleteReadOnlyRun requires Run EXECUTING")
    if plan_status is not PlanStatusV1.ACTIVE:
        raise RunTransitionRejected("CompleteReadOnlyRun requires current Plan ACTIVE")
    terminal_read_statuses = {ActionStatusV1.VERIFIED, ActionStatusV1.FAILED}
    if not action_statuses or any(
        status not in terminal_read_statuses for status in action_statuses
    ):
        raise RunTransitionRejected("CompleteReadOnlyRun requires every READ Action settled")
