from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.run.model import RunStatus
from google_work_agent.domain.run.transitions.complete_read_only_run import (
    transition_complete_read_only_run,
)


def test_complete_read_only_run_closes_parent_pair_after_all_children_settle() -> None:
    assert transition_complete_read_only_run(
        RunStatus.EXECUTING,
        plan_status=PlanStatus.ACTIVE,
        action_statuses=(ActionStatus.VERIFIED, ActionStatus.FAILED),
    ) == (RunStatus.COMPLETED, PlanStatus.COMPLETED)
