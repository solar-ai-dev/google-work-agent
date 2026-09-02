import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.complete_write_run import guard_complete_write_run
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def _guard(**changes: object) -> None:
    values = {
        "plan_status": PlanStatusV1.WAITING_APPROVAL,
        "plan_is_current": True,
        "action_statuses": (ActionStatusV1.VERIFIED,),
        "attempt_statuses": (ExecutionAttemptStatusV1.SUCCEEDED,),
        "unresolved_required_fact_count": 0,
        "external_write_count": 1,
        "cancel_intent_active": False,
    }
    values.update(changes)
    guard_complete_write_run(RunStatusV1.VERIFYING, **values)  # type: ignore[arg-type]


def test_complete_write_run__accepts_only_exact__closed_write_facts() -> None:
    _guard()
    for status in (
        ActionStatusV1.FAILED,
        ActionStatusV1.UNKNOWN_RESULT,
        ActionStatusV1.MISMATCH,
    ):
        with pytest.raises(RunTransitionRejected):
            _guard(action_statuses=(status,))
    with pytest.raises(RunTransitionRejected):
        _guard(plan_status=PlanStatusV1.ACTIVE)
    with pytest.raises(RunTransitionRejected):
        _guard(cancel_intent_active=True)
