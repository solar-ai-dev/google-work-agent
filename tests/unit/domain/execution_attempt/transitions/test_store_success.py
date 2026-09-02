from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.store_success import (
    transition_store_success,
)


def test_store_success__requires_executing_and__moves_to_executed() -> None:
    result = transition_store_success(
        ActionStatusV1.EXECUTING,
        action_version=3,
        expected_action_version=3,
        attempt_status=ExecutionAttemptStatusV1.EXECUTING,
        attempt_version=1,
        expected_attempt_version=1,
    )

    assert result.applied is True
    assert result.current_status is ActionStatusV1.EXECUTED
    assert result.attempt_status is ExecutionAttemptStatusV1.SUCCEEDED
