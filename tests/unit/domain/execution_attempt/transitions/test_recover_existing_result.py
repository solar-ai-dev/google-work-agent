from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.recover_existing_result import (
    transition_recover_existing_result,
)


def test_recover_existing_result_requires_unknown_result_and_enters_verification() -> None:
    result = transition_recover_existing_result(
        ActionStatusV1.UNKNOWN_RESULT,
        action_version=1,
        expected_action_version=1,
        attempt_status=ExecutionAttemptStatusV1.UNKNOWN_RESULT,
        attempt_version=2,
        expected_attempt_version=2,
    )

    assert result.applied is True
    assert result.current_status is ActionStatusV1.EXECUTED
    assert result.attempt_status is ExecutionAttemptStatusV1.SUCCEEDED
