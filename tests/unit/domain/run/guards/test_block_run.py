import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.block_run import guard_block_run
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def _guard(**changes: object) -> None:
    values = {
        "plan_status": PlanStatusV1.WAITING_APPROVAL,
        "plan_is_current": True,
        "review_disposition": None,
        "action_statuses": (ActionStatusV1.REJECTED,),
        "attempt_statuses": (ExecutionAttemptStatusV1.FAILED,),
    }
    values.update(changes)
    guard_block_run(RunStatusV1.WAITING_APPROVAL, **values)  # type: ignore[arg-type]


def test_block_run__requires_current_authority__and_resolved_effects() -> None:
    _guard()
    for change in (
        {"plan_is_current": False},
        {"action_statuses": (ActionStatusV1.EXECUTING,)},
        {"attempt_statuses": (ExecutionAttemptStatusV1.UNKNOWN_RESULT,)},
    ):
        with pytest.raises(RunTransitionRejected):
            _guard(**change)
