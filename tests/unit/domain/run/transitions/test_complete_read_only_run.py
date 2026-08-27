from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.run.transitions.complete_read_only_run import (
    transition_complete_read_only_run,
)


def test_complete_read_only_run_closes_parent_pair_after_all_children_settle() -> None:
    assert transition_complete_read_only_run(
        RunStatusV1.EXECUTING,
        plan_status=PlanStatusV1.ACTIVE,
        action_statuses=(ActionStatusV1.VERIFIED, ActionStatusV1.FAILED),
    ) == (RunStatusV1.COMPLETED, PlanStatusV1.COMPLETED)
