from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.execution_attempt.transitions.recover_existing_result import (
    transition_recover_existing_result,
)


def test_recover_existing_result_requires_unknown_result_and_enters_verification() -> None:
    result = transition_recover_existing_result(
        ActionStatus.UNKNOWN_RESULT,
        action_version=1,
        expected_action_version=1,
        attempt_status=ExecutionAttemptStatus.UNKNOWN_RESULT,
        attempt_version=2,
        expected_attempt_version=2,
    )

    assert result.applied is True
    assert result.current_status is ActionStatus.EXECUTED
    assert result.attempt_status is ExecutionAttemptStatus.SUCCEEDED
