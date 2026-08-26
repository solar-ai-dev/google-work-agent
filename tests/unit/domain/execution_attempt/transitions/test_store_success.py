from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.execution_attempt.transitions.store_success import (
    transition_store_success,
)


def test_store_success_requires_executing_and_moves_to_executed() -> None:
    result = transition_store_success(
        ActionStatus.EXECUTING,
        action_version=3,
        expected_action_version=3,
        attempt_status=ExecutionAttemptStatus.EXECUTING,
        attempt_version=1,
        expected_attempt_version=1,
    )

    assert result.applied is True
    assert result.current_status is ActionStatus.EXECUTED
    assert result.attempt_status is ExecutionAttemptStatus.SUCCEEDED
