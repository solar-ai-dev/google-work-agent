import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.block_run import transition_block_run


def test_block_run__applies_canonical__transition() -> None:
    assert (
        transition_block_run(
            RunStatusV1.CREATED,
            plan_status=None,
            plan_is_current=True,
            review_disposition=None,
            action_statuses=(),
            attempt_statuses=(),
        )
        is RunStatusV1.BLOCKED
    )


def test_block_run__rejects_verifying__without_block_review() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_block_run(
            RunStatusV1.VERIFYING,
            plan_status=PlanStatusV1.ACTIVE,
            plan_is_current=True,
            review_disposition="PASS",
            action_statuses=(ActionStatusV1.VERIFIED,),
            attempt_statuses=(ExecutionAttemptStatusV1.SUCCEEDED,),
        )
